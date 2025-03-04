"""
Import Reading
"""
import sys

from data_collection.management.commands import BaseShpShpImporter

class Command(BaseShpShpImporter):
    """
    Imports the Polling Station data from Reading
    """
    council_id     = 'E06000038'
    districts_name = 'polling_districts'
    stations_name  = 'polling_stations.shp'

    def district_record_to_dict(self, record):
        return {
            'internal_council_id': record[0],
            'name': record[1],
        }

    def station_record_to_dict(self, record):
        return {
            'internal_council_id': record[0],
            'postcode'           : record[-1],
            'address'            : "\n".join(record[2:-1]),
        }
    
 
