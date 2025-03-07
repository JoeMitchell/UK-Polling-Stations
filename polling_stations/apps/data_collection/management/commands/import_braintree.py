"""
Import Braintree
"""
from data_collection.management.commands import BaseShpShpImporter

class Command(BaseShpShpImporter):
    """
    Imports the Polling Station data from Braintree
    """
    council_id     = 'E07000067'
    districts_name = 'Polling_Districts'
    stations_name  = 'Polling_Stations.shp'

    def district_record_to_dict(self, record):
        return {
            'internal_council_id': record[0],
            'name': record[1],
        }

    def station_record_to_dict(self, record):
        return {
            'internal_council_id': record[0],
            'postcode'           : record[-1],
            'address'            : record[2]
        }
    
