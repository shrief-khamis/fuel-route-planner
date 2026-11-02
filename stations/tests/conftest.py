import csv

import pytest

FUEL_HEADER = ['OPIS Truckstop ID', 'Truckstop Name', 'Address', 'City', 'State', 'Rack ID', 'Retail Price']

# GeoNames rows: country, ZIP, place, state name, state code, county, county code,
# community, community code, lat, lon, accuracy.
POSTAL_CODES = [
    ['US', '74332', 'Big Cabin', 'Oklahoma', 'OK', 'Craig', '035', '', '', '36.53', '-95.22', '4'],
    ['US', '76102', 'Fort Worth', 'Texas', 'TX', 'Tarrant', '439', '', '', '32.70', '-97.30', '4'],
    ['US', '76131', 'Fort Worth', 'Texas', 'TX', 'Tarrant', '439', '', '', '32.80', '-97.36', '4'],
    ['US', '63101', 'Saint Louis', 'Missouri', 'MO', 'St. Louis City', '510', '', '', '38.63', '-90.19', '4'],
]

# The two ramps of I-44 exit 283 near Big Cabin, an exit 1 far away, and I-35W and I-35
# exits that share the number 8.
EXITS = [
    ['state', 'interstate', 'exit_ref', 'lat', 'lon', 'osm_node_id'],
    ['OK', '44', '283', '36.5612', '-95.2179', '1'],
    ['OK', '44', '283B', '36.5680', '-95.2135', '2'],
    ['OK', '44', '1', '34.1173', '-98.5204', '3'],
    ['TX', '35W', '8', '32.6500', '-97.3200', '4'],
    ['TX', '35', '8', '27.6000', '-99.4800', '5'],
]


@pytest.fixture
def data_files(tmp_path):
    """Return a function that writes the three data files and returns their paths.

    The function takes the fuel CSV rows (without the header) and, optionally, the
    postal code and exit rows to use instead of the defaults above.
    """
    def write(fuel_rows, postal_codes=POSTAL_CODES, exits=EXITS, fuel_header=FUEL_HEADER):
        """Write the files and return (fuel CSV, postal codes, exits) paths."""
        fuel = tmp_path / 'fuel.csv'
        with open(fuel, 'w', newline='') as f:
            csv.writer(f).writerows([fuel_header, *fuel_rows])
        postal = tmp_path / 'postal.txt'
        with open(postal, 'w', newline='') as f:
            csv.writer(f, delimiter='\t').writerows(postal_codes)
        exits_path = tmp_path / 'exits.csv'
        with open(exits_path, 'w', newline='') as f:
            csv.writer(f).writerows(exits)
        return fuel, postal, exits_path

    return write
