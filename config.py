# config.py
# TAP-specific configurable metadata fields and layout.
# Each field is a tuple:
#   (label, column_name, sql_type[, widget])
#
# sql_type is used for sqlite3 schema (TEXT, INT, FLOAT, DATE, TIMESTAMP, etc.).
# widget is optional; for dropdowns use:
#   "DROPDOWN('Option 1', 'Option 2', 'Option 3')"

input_fields = [
    ("Recorders",          "recorders",          "TEXT"),
    ("Date recorded",      "date_recorded",      "TIMESTAMP"),
    ("Excavation Unit",    "excavation_unit",    "TEXT", "DROPDOWN('Op1', 'Op2', 'Op3', 'Op4', 'Op5', 'Op6', 'Op7', 'Op8', 'Op9', 'Op10', 'SqA', 'SqB', 'SqC')"),
    ("T-Number",           "tnumber",            "TEXT"),
    ("Lot",                "lot",                "TEXT"),
    ("Area",               "area",               "TEXT"),
    ("Level",              "level",              "TEXT"),
    ("Excavation Date",    "excavation_date",    "DATE"),
    ("Temper",             "temper",             "TEXT"),
    ("Typology Number",    "typology_number",    "INT"),
    ("Munsell Color",      "munsell_color",      "TEXT"),
    ("Rim Diameter",       "rim_diameter",       "FLOAT"),
    ("Surface Treatment",  "surface_treatment",  "TEXT", "DROPDOWN('Burnished', 'Slip', 'Painted', 'Plain')"),
    ("Notes",              "notes",              "TEXT"),
]

layout_rows = [
    ["recorders"],
    ["excavation_unit"],
    ["tnumber"],
    ["lot"],
    ["area"],
    ["level"],
    ["excavation_date"],
    ["temper"],
    ["typology_number"],
    ["munsell_color"],
    ["rim_diameter"],
    ["surface_treatment"],
    ["notes"],
]


# layout_rows = [
#     ["recorders"],
#     ["excavation_unit", "tnumber"],
#     ["lot", "area", "level"],
#     ["excavation_date"],
#     ["temper", "typology_number"],
#     ["munsell_color", "rim_diameter"],
#     ["surface_treatment"],
#     ["notes"],
# ]


required_fields = (
    "excavation_unit",
    "tnumber",
    "lot",
    "area",
    "level",
)
