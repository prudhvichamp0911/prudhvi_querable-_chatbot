"""Geographical analysis for chat answers.

Finds the countries and cities an answer is about and turns them into a
``geo_map`` payload the frontend draws on a world map:

* database answers: country/city values in the VeloDB result rows, with
  the row's metric (or a record count when a place repeats);
* otherwise: places named in the question or in the generated answer.

Country ids are ISO 3166-1 numeric codes, the same ids as the
``world-atlas`` TopoJSON the frontend renders, so the browser never has to
match names itself.
"""

import math
import re
from collections import OrderedDict

CONTINENTS = {
    "AF": "Africa",
    "AN": "Antarctica",
    "AS": "Asia",
    "EU": "Europe",
    "NA": "North America",
    "OC": "Oceania",
    "SA": "South America",
}

# (iso numeric, name, continent, lat, lon, aliases)
_COUNTRIES = [
    ("004", "Afghanistan", "AS", 33.9, 67.7, ()),
    ("008", "Albania", "EU", 41.2, 20.2, ()),
    ("012", "Algeria", "AF", 28.0, 1.7, ()),
    ("020", "Andorra", "EU", 42.5, 1.5, ()),
    ("024", "Angola", "AF", -11.2, 17.9, ()),
    ("032", "Argentina", "SA", -38.4, -63.6, ()),
    ("051", "Armenia", "AS", 40.1, 45.0, ()),
    ("036", "Australia", "OC", -25.3, 133.8, ()),
    ("040", "Austria", "EU", 47.5, 14.6, ()),
    ("031", "Azerbaijan", "AS", 40.1, 47.6, ()),
    ("044", "Bahamas", "NA", 25.0, -77.4, ("The Bahamas",)),
    ("048", "Bahrain", "AS", 26.0, 50.6, ()),
    ("050", "Bangladesh", "AS", 23.7, 90.4, ()),
    ("052", "Barbados", "NA", 13.2, -59.5, ()),
    ("112", "Belarus", "EU", 53.7, 28.0, ()),
    ("056", "Belgium", "EU", 50.5, 4.5, ()),
    ("084", "Belize", "NA", 17.2, -88.5, ()),
    ("204", "Benin", "AF", 9.3, 2.3, ()),
    ("064", "Bhutan", "AS", 27.5, 90.4, ()),
    ("068", "Bolivia", "SA", -16.3, -63.6, ()),
    ("070", "Bosnia and Herzegovina", "EU", 43.9, 17.7, ("Bosnia", "Bosnia and Herz.")),
    ("072", "Botswana", "AF", -22.3, 24.7, ()),
    ("076", "Brazil", "SA", -14.2, -51.9, ("Brasil",)),
    ("096", "Brunei", "AS", 4.5, 114.7, ()),
    ("100", "Bulgaria", "EU", 42.7, 25.5, ()),
    ("854", "Burkina Faso", "AF", 12.2, -1.6, ()),
    ("108", "Burundi", "AF", -3.4, 29.9, ()),
    ("116", "Cambodia", "AS", 12.6, 104.9, ()),
    ("120", "Cameroon", "AF", 7.4, 12.4, ()),
    ("124", "Canada", "NA", 56.1, -106.3, ()),
    ("140", "Central African Republic", "AF", 6.6, 20.9, ("Central African Rep.",)),
    ("148", "Chad", "AF", 15.5, 18.7, ()),
    ("152", "Chile", "SA", -35.7, -71.5, ()),
    ("156", "China", "AS", 35.9, 104.2, ("PRC", "People's Republic of China")),
    ("170", "Colombia", "SA", 4.6, -74.3, ()),
    ("178", "Congo", "AF", -0.2, 15.8, ("Republic of the Congo",)),
    ("180", "DR Congo", "AF", -4.0, 21.8, ("Democratic Republic of the Congo", "Dem. Rep. Congo", "DRC")),
    ("188", "Costa Rica", "NA", 9.7, -83.8, ()),
    ("384", "Côte d'Ivoire", "AF", 7.5, -5.5, ("Ivory Coast", "Cote d'Ivoire")),
    ("191", "Croatia", "EU", 45.1, 15.2, ()),
    ("192", "Cuba", "NA", 21.5, -77.8, ()),
    ("196", "Cyprus", "EU", 35.1, 33.4, ()),
    ("203", "Czechia", "EU", 49.8, 15.5, ("Czech Republic",)),
    ("208", "Denmark", "EU", 56.3, 9.5, ()),
    ("262", "Djibouti", "AF", 11.8, 42.6, ()),
    ("214", "Dominican Republic", "NA", 18.7, -70.2, ("Dominican Rep.",)),
    ("218", "Ecuador", "SA", -1.8, -78.2, ()),
    ("818", "Egypt", "AF", 26.8, 30.8, ()),
    ("222", "El Salvador", "NA", 13.8, -88.9, ()),
    ("226", "Equatorial Guinea", "AF", 1.7, 10.3, ("Eq. Guinea",)),
    ("232", "Eritrea", "AF", 15.2, 39.8, ()),
    ("233", "Estonia", "EU", 58.6, 25.0, ()),
    ("748", "Eswatini", "AF", -26.5, 31.5, ("eSwatini", "Swaziland")),
    ("231", "Ethiopia", "AF", 9.1, 40.5, ()),
    ("238", "Falkland Islands", "SA", -51.8, -59.5, ("Falklands", "Falkland Is.")),
    ("242", "Fiji", "OC", -17.7, 178.1, ()),
    ("246", "Finland", "EU", 61.9, 25.7, ()),
    ("250", "France", "EU", 46.6, 2.4, ()),
    ("266", "Gabon", "AF", -0.8, 11.6, ()),
    ("270", "Gambia", "AF", 13.4, -15.3, ("The Gambia",)),
    ("268", "Georgia", "AS", 42.3, 43.4, ()),
    ("276", "Germany", "EU", 51.2, 10.5, ("Deutschland",)),
    ("288", "Ghana", "AF", 7.9, -1.0, ()),
    ("300", "Greece", "EU", 39.1, 21.8, ()),
    ("304", "Greenland", "NA", 71.7, -42.6, ()),
    ("320", "Guatemala", "NA", 15.8, -90.2, ()),
    ("324", "Guinea", "AF", 9.9, -9.7, ()),
    ("624", "Guinea-Bissau", "AF", 11.8, -15.2, ()),
    ("328", "Guyana", "SA", 4.9, -58.9, ()),
    ("332", "Haiti", "NA", 19.0, -72.3, ()),
    ("340", "Honduras", "NA", 15.2, -86.2, ()),
    ("344", "Hong Kong", "AS", 22.3, 114.2, ()),
    ("348", "Hungary", "EU", 47.2, 19.5, ()),
    ("352", "Iceland", "EU", 64.9, -19.0, ()),
    ("356", "India", "AS", 22.0, 79.0, ("Bharat",)),
    ("360", "Indonesia", "AS", -2.5, 118.0, ()),
    ("364", "Iran", "AS", 32.4, 53.7, ()),
    ("368", "Iraq", "AS", 33.2, 43.7, ()),
    ("372", "Ireland", "EU", 53.4, -8.2, ("Republic of Ireland",)),
    ("376", "Israel", "AS", 31.0, 34.9, ()),
    ("380", "Italy", "EU", 41.9, 12.6, ("Italia",)),
    ("388", "Jamaica", "NA", 18.1, -77.3, ()),
    ("392", "Japan", "AS", 36.2, 138.3, ()),
    ("400", "Jordan", "AS", 30.6, 36.2, ()),
    ("398", "Kazakhstan", "AS", 48.0, 66.9, ()),
    ("404", "Kenya", "AF", 0.0, 37.9, ()),
    ("414", "Kuwait", "AS", 29.3, 47.5, ()),
    ("417", "Kyrgyzstan", "AS", 41.2, 74.8, ()),
    ("418", "Laos", "AS", 19.9, 102.5, ()),
    ("428", "Latvia", "EU", 56.9, 24.6, ()),
    ("422", "Lebanon", "AS", 33.9, 35.9, ()),
    ("426", "Lesotho", "AF", -29.6, 28.2, ()),
    ("430", "Liberia", "AF", 6.4, -9.4, ()),
    ("434", "Libya", "AF", 26.3, 17.2, ()),
    ("438", "Liechtenstein", "EU", 47.2, 9.6, ()),
    ("440", "Lithuania", "EU", 55.2, 23.9, ()),
    ("442", "Luxembourg", "EU", 49.8, 6.1, ()),
    ("450", "Madagascar", "AF", -18.8, 46.9, ()),
    ("454", "Malawi", "AF", -13.3, 34.3, ()),
    ("458", "Malaysia", "AS", 4.2, 102.0, ()),
    ("462", "Maldives", "AS", 3.2, 73.2, ()),
    ("466", "Mali", "AF", 17.6, -4.0, ()),
    ("470", "Malta", "EU", 35.9, 14.4, ()),
    ("478", "Mauritania", "AF", 21.0, -10.9, ()),
    ("480", "Mauritius", "AF", -20.3, 57.6, ()),
    ("484", "Mexico", "NA", 23.6, -102.6, ("México",)),
    ("498", "Moldova", "EU", 47.4, 28.4, ()),
    ("492", "Monaco", "EU", 43.7, 7.4, ()),
    ("496", "Mongolia", "AS", 46.9, 103.8, ()),
    ("499", "Montenegro", "EU", 42.7, 19.4, ()),
    ("504", "Morocco", "AF", 31.8, -7.1, ()),
    ("508", "Mozambique", "AF", -18.7, 35.5, ()),
    ("104", "Myanmar", "AS", 21.9, 96.0, ("Burma",)),
    ("516", "Namibia", "AF", -22.9, 18.5, ()),
    ("524", "Nepal", "AS", 28.4, 84.1, ()),
    ("528", "Netherlands", "EU", 52.1, 5.3, ("Holland", "The Netherlands")),
    ("540", "New Caledonia", "OC", -20.9, 165.6, ()),
    ("554", "New Zealand", "OC", -40.9, 174.9, ()),
    ("558", "Nicaragua", "NA", 12.9, -85.2, ()),
    ("562", "Niger", "AF", 17.6, 8.1, ()),
    ("566", "Nigeria", "AF", 9.1, 8.7, ()),
    ("408", "North Korea", "AS", 40.3, 127.5, ("DPRK",)),
    ("807", "North Macedonia", "EU", 41.6, 21.7, ("Macedonia",)),
    ("578", "Norway", "EU", 61.0, 8.5, ()),
    ("512", "Oman", "AS", 21.5, 55.9, ()),
    ("586", "Pakistan", "AS", 30.4, 69.3, ()),
    ("275", "Palestine", "AS", 31.9, 35.2, ()),
    ("591", "Panama", "NA", 8.5, -80.8, ()),
    ("598", "Papua New Guinea", "OC", -6.3, 143.9, ()),
    ("600", "Paraguay", "SA", -23.4, -58.4, ()),
    ("604", "Peru", "SA", -9.2, -75.0, ()),
    ("608", "Philippines", "AS", 12.9, 121.8, ()),
    ("616", "Poland", "EU", 51.9, 19.1, ()),
    ("620", "Portugal", "EU", 39.4, -8.2, ()),
    ("630", "Puerto Rico", "NA", 18.2, -66.6, ()),
    ("634", "Qatar", "AS", 25.4, 51.2, ()),
    ("642", "Romania", "EU", 45.9, 25.0, ()),
    ("643", "Russia", "EU", 61.5, 96.0, ("Russian Federation",)),
    ("646", "Rwanda", "AF", -1.9, 29.9, ()),
    ("674", "San Marino", "EU", 43.9, 12.5, ()),
    ("682", "Saudi Arabia", "AS", 23.9, 45.1, ("KSA",)),
    ("686", "Senegal", "AF", 14.5, -14.5, ()),
    ("688", "Serbia", "EU", 44.0, 21.0, ()),
    ("694", "Sierra Leone", "AF", 8.5, -11.8, ()),
    ("702", "Singapore", "AS", 1.35, 103.8, ()),
    ("703", "Slovakia", "EU", 48.7, 19.7, ()),
    ("705", "Slovenia", "EU", 46.2, 14.995, ()),
    ("090", "Solomon Islands", "OC", -9.6, 160.2, ("Solomon Is.",)),
    ("706", "Somalia", "AF", 5.2, 46.2, ()),
    ("710", "South Africa", "AF", -30.6, 22.9, ()),
    ("410", "South Korea", "AS", 35.9, 127.8, ("Korea", "Republic of Korea")),
    ("728", "South Sudan", "AF", 6.9, 31.3, ("S. Sudan",)),
    ("724", "Spain", "EU", 40.5, -3.7, ("España",)),
    ("144", "Sri Lanka", "AS", 7.9, 80.8, ()),
    ("729", "Sudan", "AF", 12.9, 30.2, ()),
    ("740", "Suriname", "SA", 3.9, -56.0, ()),
    ("752", "Sweden", "EU", 62.2, 17.6, ()),
    ("756", "Switzerland", "EU", 46.8, 8.2, ()),
    ("760", "Syria", "AS", 34.8, 39.0, ()),
    ("158", "Taiwan", "AS", 23.7, 121.0, ()),
    ("762", "Tajikistan", "AS", 38.9, 71.3, ()),
    ("834", "Tanzania", "AF", -6.4, 34.9, ()),
    ("764", "Thailand", "AS", 15.9, 101.0, ()),
    ("626", "Timor-Leste", "AS", -8.9, 125.7, ("East Timor",)),
    ("768", "Togo", "AF", 8.6, 0.8, ()),
    ("780", "Trinidad and Tobago", "NA", 10.7, -61.2, ()),
    ("788", "Tunisia", "AF", 33.9, 9.5, ()),
    ("792", "Turkey", "AS", 39.0, 35.2, ("Türkiye", "Turkiye")),
    ("795", "Turkmenistan", "AS", 38.97, 59.6, ()),
    ("800", "Uganda", "AF", 1.4, 32.3, ()),
    ("804", "Ukraine", "EU", 48.4, 31.2, ()),
    ("784", "United Arab Emirates", "AS", 23.4, 53.8, ("UAE", "U.A.E.", "Emirates")),
    ("826", "United Kingdom", "EU", 54.0, -2.5, ("UK", "U.K.", "Great Britain", "Britain", "England", "Scotland", "Wales")),
    ("840", "United States", "NA", 39.8, -98.6, ("United States of America", "USA", "US", "U.S.", "U.S.A.")),
    ("858", "Uruguay", "SA", -32.5, -55.8, ()),
    ("860", "Uzbekistan", "AS", 41.4, 64.6, ()),
    ("548", "Vanuatu", "OC", -15.4, 166.9, ()),
    ("336", "Vatican City", "EU", 41.9, 12.45, ("Vatican", "Holy See")),
    ("862", "Venezuela", "SA", 6.4, -66.6, ()),
    ("704", "Vietnam", "AS", 14.1, 108.3, ("Viet Nam",)),
    ("732", "Western Sahara", "AF", 24.2, -12.9, ("W. Sahara",)),
    ("887", "Yemen", "AS", 15.6, 48.5, ()),
    ("894", "Zambia", "AF", -13.1, 27.8, ()),
    ("716", "Zimbabwe", "AF", -19.0, 29.2, ()),
]

# (name, iso numeric of its country, lat, lon, aliases)
_CITIES = [
    ("New York", "840", 40.71, -74.01, ("NYC", "New York City")),
    ("San Francisco", "840", 37.77, -122.42, ()),
    ("Los Angeles", "840", 34.05, -118.24, ()),
    ("Chicago", "840", 41.88, -87.63, ()),
    ("Seattle", "840", 47.61, -122.33, ()),
    ("Boston", "840", 42.36, -71.06, ()),
    ("Austin", "840", 30.27, -97.74, ()),
    ("Toronto", "124", 43.65, -79.38, ()),
    ("Vancouver", "124", 49.28, -123.12, ()),
    ("Montreal", "124", 45.50, -73.57, ()),
    ("Mexico City", "484", 19.43, -99.13, ()),
    ("São Paulo", "076", -23.55, -46.63, ("Sao Paulo",)),
    ("Buenos Aires", "032", -34.60, -58.38, ()),
    ("London", "826", 51.51, -0.13, ()),
    ("Manchester", "826", 53.48, -2.24, ()),
    ("Dublin", "372", 53.35, -6.26, ()),
    ("Paris", "250", 48.86, 2.35, ()),
    ("Berlin", "276", 52.52, 13.40, ()),
    ("Munich", "276", 48.14, 11.58, ()),
    ("Frankfurt", "276", 50.11, 8.68, ()),
    ("Amsterdam", "528", 52.37, 4.90, ()),
    ("Madrid", "724", 40.42, -3.70, ()),
    ("Barcelona", "724", 41.39, 2.17, ()),
    ("Rome", "380", 41.90, 12.50, ()),
    ("Milan", "380", 45.46, 9.19, ()),
    ("Zurich", "756", 47.37, 8.54, ()),
    ("Stockholm", "752", 59.33, 18.07, ()),
    ("Moscow", "643", 55.76, 37.62, ()),
    ("Istanbul", "792", 41.01, 28.98, ()),
    ("Dubai", "784", 25.20, 55.27, ()),
    ("Riyadh", "682", 24.71, 46.68, ()),
    ("Cairo", "818", 30.04, 31.24, ()),
    ("Casablanca", "504", 33.57, -7.59, ()),
    ("Lagos", "566", 6.52, 3.38, ()),
    ("Nairobi", "404", -1.29, 36.82, ()),
    ("Johannesburg", "710", -26.20, 28.05, ()),
    ("Cape Town", "710", -33.92, 18.42, ()),
    ("Mumbai", "356", 19.08, 72.88, ("Bombay",)),
    ("Delhi", "356", 28.61, 77.21, ("New Delhi",)),
    ("Bangalore", "356", 12.97, 77.59, ("Bengaluru",)),
    ("Hyderabad", "356", 17.39, 78.49, ()),
    ("Chennai", "356", 13.08, 80.27, ("Madras",)),
    ("Pune", "356", 18.52, 73.86, ()),
    ("Kolkata", "356", 22.57, 88.36, ("Calcutta",)),
    ("Ahmedabad", "356", 23.02, 72.57, ()),
    ("Goa", "356", 15.30, 74.12, ()),
    ("Karachi", "586", 24.86, 67.01, ()),
    ("Dhaka", "050", 23.81, 90.41, ()),
    ("Colombo", "144", 6.93, 79.86, ()),
    ("Bangkok", "764", 13.76, 100.50, ()),
    ("Jakarta", "360", -6.21, 106.85, ()),
    ("Kuala Lumpur", "458", 3.14, 101.69, ()),
    ("Manila", "608", 14.60, 120.98, ()),
    ("Beijing", "156", 39.90, 116.41, ()),
    ("Shanghai", "156", 31.23, 121.47, ()),
    ("Shenzhen", "156", 22.54, 114.06, ()),
    ("Tokyo", "392", 35.68, 139.69, ()),
    ("Osaka", "392", 34.69, 135.50, ()),
    ("Seoul", "410", 37.57, 126.98, ()),
    ("Sydney", "036", -33.87, 151.21, ()),
    ("Melbourne", "036", -37.81, 144.96, ()),
    ("Auckland", "554", -36.85, 174.76, ()),
    ("Washington", "840", 38.91, -77.04, ("Washington D.C.", "Washington DC")),
    ("Houston", "840", 29.76, -95.37, ()),
    ("Dallas", "840", 32.78, -96.80, ()),
    ("Miami", "840", 25.76, -80.19, ()),
    ("Atlanta", "840", 33.75, -84.39, ()),
    ("Denver", "840", 39.74, -104.99, ()),
    ("Ottawa", "124", 45.42, -75.70, ()),
    ("Calgary", "124", 51.05, -114.07, ()),
    ("Rio de Janeiro", "076", -22.91, -43.17, ()),
    ("Bogotá", "170", 4.71, -74.07, ("Bogota",)),
    ("Lima", "604", -12.05, -77.04, ()),
    ("Santiago", "152", -33.45, -70.67, ()),
    ("Edinburgh", "826", 55.95, -3.19, ()),
    ("Birmingham", "826", 52.49, -1.89, ()),
    ("Brussels", "056", 50.85, 4.35, ()),
    ("Rotterdam", "528", 51.92, 4.48, ()),
    ("Hamburg", "276", 53.55, 9.99, ()),
    ("Lyon", "250", 45.76, 4.84, ()),
    ("Geneva", "756", 46.20, 6.14, ()),
    ("Vienna", "040", 48.21, 16.37, ()),
    ("Lisbon", "620", 38.72, -9.14, ()),
    ("Copenhagen", "208", 55.68, 12.57, ()),
    ("Oslo", "578", 59.91, 10.75, ()),
    ("Helsinki", "246", 60.17, 24.94, ()),
    ("Warsaw", "616", 52.23, 21.01, ()),
    ("Prague", "203", 50.08, 14.44, ()),
    ("Budapest", "348", 47.50, 19.04, ()),
    ("Athens", "300", 37.98, 23.73, ()),
    ("Kyiv", "804", 50.45, 30.52, ("Kiev",)),
    ("Tel Aviv", "376", 32.09, 34.78, ()),
    ("Abu Dhabi", "784", 24.45, 54.38, ()),
    ("Doha", "634", 25.29, 51.53, ()),
    ("Rabat", "504", 34.02, -6.83, ()),
    ("Marrakesh", "504", 31.63, -7.98, ("Marrakech",)),
    ("Accra", "288", 5.60, -0.19, ()),
    ("Addis Ababa", "231", 9.03, 38.74, ()),
    ("Gurugram", "356", 28.46, 77.03, ("Gurgaon",)),
    ("Noida", "356", 28.54, 77.39, ()),
    ("Jaipur", "356", 26.91, 75.79, ()),
    ("Kochi", "356", 9.93, 76.27, ("Cochin",)),
    ("Islamabad", "586", 33.68, 73.05, ()),
    ("Lahore", "586", 31.55, 74.34, ()),
    ("Kathmandu", "524", 27.72, 85.32, ()),
    ("Hanoi", "704", 21.03, 105.85, ()),
    ("Ho Chi Minh City", "704", 10.82, 106.63, ("Saigon",)),
    ("Taipei", "158", 25.03, 121.57, ()),
    ("Brisbane", "036", -27.47, 153.03, ()),
    ("Perth", "036", -31.95, 115.86, ()),
    ("Wellington", "554", -41.29, 174.78, ()),
]

# Demonyms, matched in free text only ("German companies" -> Germany).
_DEMONYMS = {
    "American": "840", "Canadian": "124", "Mexican": "484", "Brazilian": "076", "Argentine": "032",
    "Argentinian": "032", "Chilean": "152", "Colombian": "170", "Peruvian": "604",
    "British": "826", "English": "826", "Scottish": "826", "Welsh": "826", "Irish": "372",
    "French": "250", "German": "276", "Dutch": "528", "Belgian": "056", "Swiss": "756",
    "Austrian": "040", "Italian": "380", "Spanish": "724", "Portuguese": "620", "Swedish": "752",
    "Norwegian": "578", "Danish": "208", "Finnish": "246", "Polish": "616", "Czech": "203",
    "Hungarian": "348", "Greek": "300", "Ukrainian": "804", "Russian": "643", "Turkish": "792",
    "Israeli": "376", "Saudi": "682", "Emirati": "784", "Qatari": "634", "Egyptian": "818",
    "Moroccan": "504", "Nigerian": "566", "Kenyan": "404", "South African": "710",
    "Indian": "356", "Pakistani": "586", "Bangladeshi": "050", "Sri Lankan": "144", "Nepali": "524",
    "Chinese": "156", "Japanese": "392", "Korean": "410", "South Korean": "410", "Taiwanese": "158",
    "Singaporean": "702", "Malaysian": "458", "Indonesian": "360", "Thai": "764", "Vietnamese": "704",
    "Filipino": "608", "Australian": "036", "New Zealander": "554",
}
# Demonyms that are also ordinary words ("polish the report"): capitalised only.
_AMBIGUOUS_DEMONYMS = {"polish", "english", "turkish", "french", "swiss", "danish", "chinese", "indian"}

# Names that are also ordinary words or person names: only matched in free
# text when capitalised (data values are matched exactly regardless).
_AMBIGUOUS = {"chad", "jordan", "georgia", "turkey", "guinea", "niger", "us", "korea", "congo", "goa"}

COUNTRIES = {}
CITIES = {}
_LOOKUP = {}  # normalised name -> ("country"|"city", key)


def _norm(text):
    text = str(text).strip().lower().replace("&", "and")
    text = re.sub(r"[\s_]+", " ", text)
    return text.strip(" .")


for _id, _name, _cont, _lat, _lon, _aliases in _COUNTRIES:
    COUNTRIES[_id] = {"id": _id, "name": _name, "continent": _cont, "lat": _lat, "lon": _lon}
    for _alias in (_name, *_aliases):
        _LOOKUP[_norm(_alias)] = ("country", _id)

for _name, _country, _lat, _lon, _aliases in _CITIES:
    CITIES[_name] = {"name": _name, "country": _country, "lat": _lat, "lon": _lon}
    for _alias in (_name, *_aliases):
        _LOOKUP.setdefault(_norm(_alias), ("city", _name))

_TEXT_ONLY = {_norm(_demonym): ("country", _id) for _demonym, _id in _DEMONYMS.items()}

_ALL_NAMES = sorted(
    {alias for _c in _COUNTRIES for alias in (_c[1], *_c[5])}
    | {alias for _c in _CITIES for alias in (_c[0], *_c[4])}
    | set(_DEMONYMS),
    key=len,
    reverse=True,
)
_TEXT_PATTERN = re.compile(
    r"(?<![\w.])(" + "|".join(re.escape(name) for name in _ALL_NAMES) + r")(?![\w])",
    re.IGNORECASE,
)


def lookup(value):
    """("country"|"city", key) for a place name, or None."""

    if not isinstance(value, str) or not value.strip() or len(value) > 60:
        return None
    return _LOOKUP.get(_norm(value))


def places_in_text(text):
    """Places named in free text, in order of first mention."""

    found = OrderedDict()
    # "North American", "Indian subcontinent": the region wins over the demonym.
    region_spans = [m.span(1) for m in _REGION_PATTERN.finditer(text or "")]
    for match in _TEXT_PATTERN.finditer(text or ""):
        word = match.group(1)
        key = _norm(word)
        if key in _TEXT_ONLY and any(a <= match.start(1) and match.end(1) <= b for a, b in region_spans):
            continue
        if (key in _AMBIGUOUS or key in _AMBIGUOUS_DEMONYMS) and not word[:1].isupper():
            continue
        if key in {"us", "uk", "uae", "usa", "drc", "prc", "ksa", "dprk"} and word != word.upper():
            continue  # "us" the pronoun, not the country
        hit = _LOOKUP.get(key) or _TEXT_ONLY.get(key)
        if hit:
            found.setdefault(hit, None)
    return list(found)


# ---------------------------------------------------------------- regions

_MIDDLE_EAST = {"048", "818", "364", "368", "376", "400", "414", "422", "512", "275", "634", "682", "760",
                "792", "784", "887"}
_EU27 = {"040", "056", "100", "191", "196", "203", "208", "233", "246", "250", "276", "300", "348", "372",
         "380", "428", "440", "442", "470", "528", "616", "620", "642", "703", "705", "724", "752"}


def _continent(code):
    return {cid for cid, country in COUNTRIES.items() if country["continent"] == code}


# name -> (aliases, country ids). Continents come from the country table;
# business regions (APAC, EMEA, LATAM, ...) are the usual groupings.
_REGIONS = {
    "Europe": (("Europe", "European"), _continent("EU")),
    "Asia": (("Asia", "Asian"), _continent("AS")),
    "Africa": (("Africa", "African"), _continent("AF")),
    "North America": (("North America", "North American"), {"840", "124", "484"}),
    "South America": (("South America", "South American"), _continent("SA")),
    "Oceania": (("Oceania", "Australasia"), _continent("OC")),
    "Americas": (("Americas",), _continent("NA") | _continent("SA")),
    "Middle East": (("Middle East", "Middle Eastern", "MENA", "GCC"), _MIDDLE_EAST),
    "APAC": (("APAC", "Asia Pacific", "Asia-Pacific"), (_continent("AS") | _continent("OC")) - _MIDDLE_EAST),
    "EMEA": (("EMEA",), _continent("EU") | _continent("AF") | _MIDDLE_EAST),
    "Latin America": (("Latin America", "LATAM", "LatAm"),
                      _continent("SA") | {"484", "320", "084", "340", "222", "558", "188", "591", "192",
                                          "214", "332", "630"}),
    "European Union": (("European Union", "EU"), _EU27),
    "Nordics": (("Nordics", "Nordic", "Scandinavia", "Scandinavian"), {"208", "246", "352", "578", "752"}),
    "DACH": (("DACH",), {"276", "040", "756"}),
    "Benelux": (("Benelux",), {"056", "528", "442"}),
    "Southeast Asia": (("Southeast Asia", "South East Asia", "South-East Asia", "ASEAN"),
                       {"096", "116", "360", "418", "458", "104", "608", "702", "764", "626", "704"}),
    "South Asia": (("South Asia", "South Asian", "Indian subcontinent"),
                   {"004", "050", "064", "356", "462", "524", "586", "144"}),
}
# Short codes that are also ordinary words ("eu", "dach"): upper case only.
_REGION_UPPER_ONLY = {"eu", "dach", "gcc", "mena", "apac", "emea", "latam", "asean"}

_REGION_LOOKUP = {_norm(alias): name for name, (aliases, _) in _REGIONS.items() for alias in aliases}
_REGION_PATTERN = re.compile(
    r"(?<![\w.-])("
    + "|".join(re.escape(a) for a in sorted({a for aliases, _ in _REGIONS.values() for a in aliases},
                                            key=len, reverse=True))
    + r")(?![\w-])",
    re.IGNORECASE,
)


def _centroid(ids):
    x = y = z = 0.0
    for cid in ids:
        lat, lon = math.radians(COUNTRIES[cid]["lat"]), math.radians(COUNTRIES[cid]["lon"])
        x += math.cos(lat) * math.cos(lon)
        y += math.cos(lat) * math.sin(lon)
        z += math.sin(lat)
    return (round(math.degrees(math.atan2(z, math.hypot(x, y))), 2),
            round(math.degrees(math.atan2(y, x)), 2))


def regions_in_text(text):
    """Continents and business regions named in free text, in order of mention."""

    found = OrderedDict()
    for match in _REGION_PATTERN.finditer(text or ""):
        word = match.group(1)
        key = _norm(word)
        if key in _REGION_UPPER_ONLY and word != word.upper() and word not in {"LatAm"}:
            continue
        region = _REGION_LOOKUP.get(key)
        if region:
            found.setdefault(region, None)
    return list(found)


def region_countries(name):
    """Country names of a region, alphabetical."""

    return sorted(COUNTRIES[cid]["name"] for cid in _REGIONS[name][1])


def _region_record(name):
    ids = sorted(_REGIONS[name][1])
    lat, lon = _centroid(ids)
    return {"name": name, "ids": ids, "lat": lat, "lon": lon}


def query_hints(question):
    """Geography notes for the query planner.

    The data stores countries, not continents or regions, so "companies in
    Europe" must become ``country: {$in: [...]}`` and "German companies" a
    match on "Germany". Returns "" when the question has no geography.
    """

    notes = []
    for region in regions_in_text(question):
        notes.append(
            f'- "{region}" is not a stored value. Filter the country field with $in over these '
            f"country names (only those present in the data will match): {', '.join(region_countries(region))}."
        )
    region_spans = [m.span(1) for m in _REGION_PATTERN.finditer(question or "")]
    demonyms = OrderedDict()
    for match in _TEXT_PATTERN.finditer(question or ""):
        word = match.group(1)
        key = _norm(word)
        if key not in _TEXT_ONLY or any(a <= match.start(1) and match.end(1) <= b for a, b in region_spans):
            continue
        if word[:1].isupper() or key not in _AMBIGUOUS_DEMONYMS:
            demonyms.setdefault(word, COUNTRIES[_TEXT_ONLY[key][1]]["name"])
    for word, country in demonyms.items():
        notes.append(f'- "{word}" means the country value "{country}".')
    if re.search(r"\b(continents?|regions?|regional)\b", question or "", re.IGNORECASE):
        notes.append(
            "- There is no continent or region field. For a breakdown by continent or region, group by "
            "the country field; the app rolls countries up into continents on the globe."
        )
    return "Geography notes:\n" + "\n".join(notes) if notes else ""


# ---------------------------------------------------------------- results

_PLACE_KEYS = ("country", "nation", "location", "region", "city", "place", "market", "_id")
_SKIP_METRIC = re.compile(r"(^_?id$|_id$|^year$|^month$|^day$|zip|phone|postal)", re.IGNORECASE)


def _flatten(row):
    flat = {}
    for key, value in row.items():
        if isinstance(value, dict):
            for inner, inner_value in value.items():
                flat[inner] = inner_value
        else:
            flat[key] = value
    return flat


def _place_in_row(row):
    ordered = sorted(
        row.items(),
        key=lambda item: next(
            (i for i, hint in enumerate(_PLACE_KEYS) if hint in item[0].lower()), len(_PLACE_KEYS)
        ),
    )
    for key, value in ordered:
        hit = lookup(value)
        if hit:
            return key, hit
    return None, None


def _metric_in_row(row, place_key):
    for key, value in row.items():
        if key == place_key or isinstance(value, bool) or _SKIP_METRIC.search(key):
            continue
        if isinstance(value, (int, float)):
            return key, float(value)
    return None, None


def _label(key):
    if not key:
        return "Records"
    text = key.replace("_", " ").strip()
    text = re.sub(r"\busd\b", "(USD)", text, flags=re.IGNORECASE)
    return text[:1].upper() + text[1:]


def _place_record(hit):
    kind, key = hit
    if kind == "country":
        country = COUNTRIES[key]
        return {
            "key": f"country:{key}",
            "kind": "country",
            "id": key,
            "name": country["name"],
            "continent": CONTINENTS[country["continent"]],
            "lat": country["lat"],
            "lon": country["lon"],
        }
    city = CITIES[key]
    country = COUNTRIES[city["country"]]
    return {
        "key": f"city:{key}",
        "kind": "city",
        "id": city["country"],
        "name": city["name"],
        "country": country["name"],
        "continent": CONTINENTS[country["continent"]],
        "lat": city["lat"],
        "lon": city["lon"],
    }


def _from_rows(rows):
    """Places, values and metric label from VeloDB result rows."""

    places = OrderedDict()
    metric_key, any_metric, repeats = None, False, False
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        row = _flatten(raw)
        place_key, hit = _place_in_row(row)
        if not hit:
            continue
        key, value = _metric_in_row(row, place_key)
        if key:
            metric_key = metric_key or key
            any_metric = True
        record = places.get(hit)
        if record is None:
            places[hit] = {"value": value, "rows": 1}
        else:
            repeats = True
            record["rows"] += 1
            if value is not None:
                record["value"] = (record["value"] or 0) + value

    if not places:
        return [], None

    # A place that appears in many raw documents (a find) is counted, not summed.
    use_count = (repeats and not _looks_grouped(rows)) or not any_metric
    if use_count and not repeats:
        # A plain list of places (e.g. a distinct): mark them, no values.
        return [_place_record(hit) for hit in places], None
    result = []
    for hit, record in places.items():
        place = _place_record(hit)
        place["value"] = float(record["rows"]) if use_count else record["value"]
        result.append(place)
    return result, "Records" if use_count else _label(metric_key)


def _looks_grouped(rows):
    return any(isinstance(row, dict) and "_id" in row for row in rows)


def _summary(places, metric):
    """Short, deterministic geographic insights (no LLM call)."""

    valued = [p for p in places if isinstance(p.get("value"), (int, float))]
    insights = []
    if not valued:
        if len(places) == 1:
            place = places[0]
            where = f", {place['country']}" if place["kind"] == "city" else ""
            insights.append({"tone": "lead", "title": f"{place['name']}{where}",
                             "detail": f"Located in {place['continent']}."})
        elif places:
            continents = sorted({p["continent"] for p in places})
            insights.append({"tone": "spread", "title": f"{len(places)} places marked",
                             "detail": f"Across {', '.join(continents)}."})
        return insights

    valued.sort(key=lambda p: p["value"], reverse=True)
    total = sum(p["value"] for p in valued)
    leader = valued[0]
    if total > 0 and len(valued) > 1:
        share = leader["value"] / total
        insights.append({"tone": "lead", "title": f"{leader['name']} leads",
                         "detail": f"{share:.0%} of total {metric.lower()}."})
        runner = valued[1]
        if runner["value"] > 0:
            ratio = leader["value"] / runner["value"]
            insights.append({"tone": "gap", "title": f"{ratio:.1f}× the runner-up",
                             "detail": f"{leader['name']} vs {runner['name']}."})
        if len(valued) >= 4:
            top3 = sum(p["value"] for p in valued[:3]) / total
            insights.append({"tone": "concentration", "title": f"Top 3 hold {top3:.0%}",
                             "detail": f"of {len(valued)} places in the result."})
    elif len(valued) == 1:
        insights.append({"tone": "lead", "title": leader["name"],
                         "detail": f"{metric}: {leader['value']:,.0f}"})

    by_continent = {}
    for place in valued:
        by_continent[place["continent"]] = by_continent.get(place["continent"], 0) + place["value"]
    if len(by_continent) > 1 and total > 0:
        continent, value = max(by_continent.items(), key=lambda item: item[1])
        insights.append({"tone": "region", "title": f"{continent} dominates",
                         "detail": f"{value / total:.0%} across "
                                   f"{sum(1 for p in valued if p['continent'] == continent)} places."})
    return insights[:4]


def build_geo_payload(question, rows=None, answer_text=None):
    """``geo_map`` tool result, or None when the answer has no geography.

    Continents and regions named in the question (Europe, APAC, ...) come
    back as ``regions`` so the globe can tint them and fly there, even when
    the answer itself is a single number.
    """

    regions = [_region_record(name) for name in regions_in_text(question)]
    places, metric, source = [], None, None
    if rows:
        places, metric = _from_rows(rows)
        source = "database" if places else None

    if not places:
        hits = places_in_text(question)
        source = "question" if hits else None
        if not hits and answer_text:
            hits = places_in_text(answer_text)[:12]
            source = "answer" if hits else None
        places = [_place_record(hit) for hit in hits]
        # "How many companies are in India?" -> count 38 belongs to India.
        if len(places) == 1 and rows and len(rows) == 1 and isinstance(rows[0], dict):
            key, value = _metric_in_row(_flatten(rows[0]), None)
            if key:
                places[0]["value"], metric = value, _label(key)

    if not places and not regions:
        return None

    total = sum(p["value"] for p in places if isinstance(p.get("value"), (int, float)))
    for place in places:
        value = place.get("value")
        place["share"] = round(value / total, 4) if total and isinstance(value, (int, float)) else None

    if places:
        insights = _summary(places, metric or "Records")
    else:
        source, insights = "question", _region_summary(regions, rows)

    return {
        "source": source,
        "metric": metric,
        "total": total or None,
        "places": places,
        "regions": regions,
        "continents": sorted({p["continent"] for p in places} or {r["name"] for r in regions}),
        "insights": insights,
    }


def _region_summary(regions, rows):
    """Insights for an answer about a whole region ("How many companies are in Europe?")."""

    insights = []
    if rows and len(rows) == 1 and isinstance(rows[0], dict):
        key, value = _metric_in_row(_flatten(rows[0]), None)
        if key:
            shown = f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
            insights.append({"tone": "lead", "title": " · ".join(r["name"] for r in regions),
                             "detail": f"{_label(key)}: {shown}"})
    for region in regions[:2]:
        insights.append({"tone": "region", "title": region["name"],
                         "detail": f"{len(region['ids'])} countries highlighted on the globe."})
    return insights[:3]
