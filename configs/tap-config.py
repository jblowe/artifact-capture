# config.py
# TAP configuration for the Artifact Capture app.
#
# object_types defines the metadata schema and layout per object type.
# Each field tuple is:
#   (label, column_name, sql_type[, widget])
#
# widget is optional; for dropdowns use:
#   "DROPDOWN('Option 1', 'Option 2')"
#
# Banner / UI config:
APP_BRAND = "TAP"
APP_SUBTITLE = ""  # optional, shown smaller in the banner
APP_LOGO = "tap-logo-small-v2.png"
ADMIN_LABEL = "Admin"  # label used in admin page titles
FILENAME_PREFIX = "TAP"  # prefix used for generated filenames

BANNER_BG = '#A51931'  # navbar background
BANNER_FG = '#ffffff'  # navbar text
BANNER_ACCENT = "#60a5fa"  # active link underline/accent
SHOW_LOGO = True  # looks for static/images/logo.svg

object_types = {
    'artifacts':
        {'label': 'Artifacts',
         'input_fields': [
             ("Recorders", "recorders", "TEXT",
              "DROPDOWN('jbl', 'km', 'vcp', 'cw', 'xx')"),
             ("Date recorded", "date_recorded", "TIMESTAMP"),
             ("Excavation Unit", "excavation_unit", "TEXT",
              "DROPDOWN('Op1', 'Op2', 'Op3', 'Op4', 'Op5', 'Op6', 'Op7', 'Op8', 'Op9', 'Op10', 'SqA', 'SqB', 'SqC')"),
             ("T-Number", "tnumber", "TEXT"),
             ("Lot", "lot", "TEXT"),
             ("Area", "area", "TEXT"),
             ("Level", "level", "TEXT"),
             ("Excavation Date", "excavation_date", "DATE"),
             ("Temper", "temper", "TEXT"),
             ("Typology Number", "typology_number", "INT"),
             ("Munsell Color", "munsell_color", "TEXT"),
             ("Rim Diameter", "rim_diameter", "FLOAT"),
             ("Surface Treatment", "surface_treatment", "TEXT",
              "DROPDOWN('Burnished', 'Slip', 'Painted', 'Plain')"),
             ("Notes", "notes", "TEXT"),
         ],
         'layout_rows': [
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
         ],
         'required_fields': (
             "excavation_unit",
             "tnumber",
             "lot",
             "area",
             "level",
         )
         },
}
