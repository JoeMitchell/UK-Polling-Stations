"""
Defines the base importer classes to override
"""
import csv
import json
import glob
import os
import shapefile
import sys
import tempfile
import zipfile

from collections import namedtuple

from django.core.management.base import BaseCommand
from django.contrib.gis import geos
from django.contrib.gis.gdal import DataSource
from django.contrib.gis.geos import Point, GEOSGeometry

from councils.models import Council
from pollingstations.models import PollingStation, PollingDistrict


class CsvHelper:

    def __init__(self, filepath):
        self.filepath = filepath

    def parseCsv(self):
        file = open(self.filepath, 'rt')
        reader = csv.reader(file)
        header = next(reader)

        # mimic the data structure generated by ffs so existing import scripts don't break
        clean = [s.strip().lower().replace(' ', '_').replace('.', '_').replace('(', '').replace(')', '') for s in header]
        RowKlass = namedtuple('RowKlass', clean)

        data = []
        for row in map(RowKlass._make, reader):
            data.append(row)

        file.close()
        return data


class BaseImporter(BaseCommand):
    srid           = 27700
    districts_srid = None

    council_id       = None
    base_folder_path = None
    stations_name    = "polling_places"
    districts_name   = "polling_districts"

    def postcode_from_address(self, address): return address.split(',')[-1]
    def string_to_newline_addr(self, string): return "\n".join(string.split(',')[:-1])

    def get_srid(self, type=None):
        if type == 'districts' and self.districts_srid is not None:
            return self.districts_srid
        else:
            return self.srid

    def clean_poly(self, poly):
        if isinstance(poly, geos.Polygon):
            poly = geos.MultiPolygon(poly, srid=self.get_srid('districts'))
            return poly
        # try:
        #     polygons = wkt[18:-3].split(')), ((')
        #     WKT = ""
        #     for polygon in polygons:
        #         points = polygon.split(',')
        #         cleaned_points = ""
        #         for point in points:
        #             split_points = point.strip().split(' ')
        #             x = split_points[0]
        #             y = split_points[1]
        #             cleaned_points += "%s %s, " % (x,y)
        #         cleaned_points = "((%s))," % cleaned_points[:-2]
        #
        #         WKT += cleaned_points
        # except:
        #     WKT = wkt
        return poly

    def import_data(self):
        """
        There are two types of import - districts and stations.
        """
        self.import_polling_districts()
        self.import_polling_stations()

    def add_polling_district(self, district_info):
        PollingDistrict.objects.update_or_create(
            council=self.council,
            internal_council_id=district_info.get('internal_council_id', 'none'),
            defaults=district_info,
        )

    def add_polling_station(self, station_info):
        PollingStation.objects.update_or_create(
            council=self.council,
            internal_council_id=station_info['internal_council_id'],
            defaults=station_info,
        )

    def import_polling_stations(self):
        stations = os.path.join(self.base_folder_path, self.stations_name)

        helper = CsvHelper(stations)
        data = helper.parseCsv()
        for row in data:
            station_info = self.station_record_to_dict(row)
            if station_info is None:
                continue
            if 'council' not in station_info:
                station_info['council'] = self.council

            self.add_polling_station(station_info)

    def handle(self, *args, **kwargs):
        if self.council_id is None:
            self.council_id = args[0]

        self.council = Council.objects.get(pk=self.council_id)

        # Delete old data for this council
        PollingStation.objects.filter(council=self.council).delete()
        PollingDistrict.objects.filter(council=self.council).delete()

        if self.base_folder_path is None:
            self.base_folder_path = os.path.abspath(
                glob.glob('data/{0}-*'.format(self.council_id))[0]
            )

        self.import_data()


class BaseShpImporter(BaseImporter):
    """
    Import data where districts are shapefiles and stations are csv
    """
    def import_polling_districts(self):
        sf = shapefile.Reader("{0}/{1}".format(
            self.base_folder_path,
            self.districts_name
            ))
        for district in sf.shapeRecords():
            district_info = self.district_record_to_dict(district.record)
            if 'council' not in district_info:
                district_info['council'] = self.council

            geojson = json.dumps(district.shape.__geo_interface__)
            poly = self.clean_poly(GEOSGeometry(geojson, srid=self.get_srid('districts')))
            district_info['area'] = poly
            self.add_polling_district(district_info)


class BaseShpShpImporter(BaseShpImporter):
    """
    Import data where both stations and polling districts are
    shapefiles.
    """
    def import_polling_stations(self):
        import_polling_station_shapefiles(self)


def import_polling_station_shapefiles(importer):
    sf = shapefile.Reader("{0}/{1}".format(
        importer.base_folder_path,
        importer.stations_name
        ))
    for station in sf.shapeRecords():
        station_info = importer.station_record_to_dict(station.record)
        if station_info is not None:
            if 'council' not in station_info:
                station_info['council'] = importer.council


            station_info['location'] = Point(
                *station.shape.points[0],
                srid=importer.get_srid())
            importer.add_polling_station(station_info)



class BaseJasonImporter(BaseImporter):
    """
    Import those councils whose data is JASON.
    """

    def import_polling_districts(self):
        districtsfile = os.path.join(self.base_folder_path, self.districts_name)
        districts = json.load(open(districtsfile))

        for district in districts['features']:
            district_info = self.district_record_to_dict(district)
            if 'council' not in district_info:
                district_info['council'] = self.council

            if district_info is None:
                continue
            poly = self.clean_poly(GEOSGeometry(json.dumps(district['geometry']), srid=self.get_srid('districts')))
            district_info['area'] = poly
            self.add_polling_district(district_info)


class BaseKamlImporter(BaseImporter):
    """
    Import those councils whose data is KML
    """

    districts_srid = 4326

    def strip_z_values(self, geojson):
        districts = json.loads(geojson)
        districts['type'] = 'Polygon'
        for points in districts['coordinates'][0][0]:
            if len(points) == 3:
                points.pop()
        districts['coordinates'] = districts['coordinates'][0]
        return json.dumps(districts)

    def district_record_to_dict(self, record):
        geojson = self.strip_z_values(record.geom.geojson)
        poly = self.clean_poly(GEOSGeometry(geojson, srid=self.get_srid('districts')))
        return {
            'internal_council_id': record['Name'].value,
            'name'               : record['Name'].value,
            'area'               : poly
        }

    def import_polling_districts(self):
        districtsfile = os.path.join(self.base_folder_path, self.districts_name)

        def add_kml_district(kml):
            ds = DataSource(kml)
            lyr = ds[0]
            for feature in lyr:
                district_info = self.district_record_to_dict(feature)
                if 'council' not in district_info:
                    district_info['council'] = self.council

                self.add_polling_district(district_info)

        if not districtsfile.endswith('.kmz'):
            add_kml_district(districtsfile)
            return

        # It's a .kmz file !
        # Because the C lib that the django DataSource is wrapping
        # expects a file on disk, let's extract the actual KML to a tmpfile.
        kmz = zipfile.ZipFile(districtsfile, 'r')
        kmlfile = kmz.open('doc.kml', 'r')

        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(kmlfile.read())
            add_kml_district(tmp.name)
            tmp.close()
