# config.py
# TAP configuration for the Artifact Capture app.
#
# object_types defines the metadata schema and layout per object type.
# Each field tuple is:
#   (label, column_name, sql_type[, widget])
#
# widget is optional; for dropdowns use:
#   'DROPDOWN('Option 1', 'Option 2')'
#
# Banner / UI config:
APP_BRAND = 'TAP'
APP_SUBTITLE = ''  # optional, shown smaller in the banner
APP_LOGO = 'tap-logo-small-v2.png'
ADMIN_LABEL = 'Admin'  # label used in admin page titles
FILENAME_PREFIX = 'TAP'  # prefix used for generated filenames

BANNER_BG = '#A51931'  # navbar background
BANNER_FG = '#ffffff'  # navbar text
BANNER_ACCENT = '#60a5fa'  # active link underline/accent
SHOW_LOGO = True  # looks for static/images/logo.svg

RECORDERS = "DROPDOWN('jb', 'karen', 'mapan', 'nic', 'pai', 'susan', 'toey', 'vince')"

object_types = {

    'bags':
        {'label': 'Bag',
         'input_fields': [
             ('Season', 'season', 'TEXT',
              "DROPDOWN('TAP 86', 'TAP 90', 'TAP 92', 'TAP 94')"),
             ('Recorders', 'recorders', 'TEXT', RECORDERS),
             ('T-Number', 'tnumber', 'TEXT'),
             ('Context', 'context', 'TEXT'),
             ('Date recorded', 'date_recorded', 'TIMESTAMP'),
             ('Notes', 'notes', 'TEXT'),
         ],
         'layout_rows': [
             ['recorders'],
             ['season'],
             ['tnumber'],
             ['context'],
             ['date_recorded'],
             ['notes'],
         ],
         'required_fields': (
             'season',
             'tnumber',
             'context',
             'date_recorded',
         )
         },

    'artifacts':
        {'label': 'Artifact',
         'input_fields': [
             ('Recorders', 'recorders', 'TEXT', RECORDERS),
             ('Date recorded', 'date_recorded', 'TIMESTAMP'),
             ('Excavation Unit', 'excavation_unit', 'TEXT',
              # 'DROPDOWN('Op1', 'Op2', 'Op3', 'Op4', 'Op5', 'Op6', 'Op7', 'Op8', 'Op9', 'Op10', 'SqA', 'SqB', 'SqC')'),
              "DROPDOWN('SqA', 'SqC', 'Op1')"),
             ('T-Number', 'tnumber', 'TEXT'),
             ('Area', 'area', 'TEXT'),
             ('Level', 'level', 'TEXT'),
             ('Excavation Date', 'excavation_date', 'DATE'),
             ('Vessel Type', 'vessel_type', 'TEXT',
              "DROPDOWN('hole-mouthed jar', 'open-mouthed jar', 'collared jar')"),
             ('Temper', 'temper', 'TEXT',
              "DROPDOWN('T1', 'T2', 'T3','T4', 'T5', 'T6', 'T7')"),
             ('Typology Number', 'typology_number', 'INT'),
             ('Collar Height', 'collar_height', 'FLOAT'),
             ('Rim Diameter', 'rim_diameter', 'FLOAT'),
             ('Surface Treatment', 'surface_treatment', 'TEXT',
              "DROPDOWN('red slip',  'black slip',  'cord marking',  'cross-hatch incising',  'interior red slip',  'exterior red slip',  'both sides red slip',  'parallel incised',  'other incised',  'multiple (incising, cord)')"),
             ('Notes', 'notes', 'TEXT'),
         ],
         'layout_rows': [
             ['recorders'],
             ['excavation_unit'],
             ['area'],
             ['level'],
             ['excavation_date'],
             ['tnumber'],
             ['surface_treatment'],
             ['temper'],
             ['typology_number'],
             # ['munsell_color'],
             ['collar_height'],
             ['rim_diameter'],
             ['notes'],
         ],
         'required_fields': (
             'excavation_unit',
             'tnumber',
             'area',
             'level',
         )
         },

    'photographs':
        {'label': 'Photograph',
         'input_fields': [
             ('Photographer', 'photographer', 'TEXT', RECORDERS),
             ('Site Name', 'site_name', 'TEXT'),
             ('Shot type', 'shot_type', 'TEXT'),
             ('Date recorded', 'date_recorded', 'TIMESTAMP'),
         ],
         'layout_rows': [
             ['photographer'],
             ['site_name'],
             ['comments'],
             ['date_recorded'],
         ],
         'required_fields': (
             'photographer',
             'site_name',
             'shot_type',
         )
         },
}
