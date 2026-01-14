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
DATE_FORMAT = '%Y-%m-%d'  # storage format for DATE fields

BANNER_BG = '#A51931'  # navbar background
BANNER_FG = '#ffffff'  # navbar text
BANNER_ACCENT = '#60a5fa'  # active link underline/accent
SHOW_LOGO = True  # looks for static/images/logo.svg

RECORDERS = "RADIO('JB', 'Karen', 'Maprang', 'Nick', 'Non', 'Phai', 'Susan', 'Toey', 'Vince')"
SEASON = ('Season', 'season', 'TEXT',
          "DROPDOWN('TAP 86', 'TAP 90', 'TAP 92', 'TAP 94')")

# ('Excavation Unit', 'excavation_unit', 'TEXT',
#  # 'DROPDOWN('Op1', 'Op2', 'Op3', 'Op4', 'Op5', 'Op6', 'Op7', 'Op8', 'Op9', 'Op10', 'SqA', 'SqB', 'SqC')'),
#  "DROPDOWN('SqA', 'SqC', 'Op1')"),
# ('T-Number', 'tnumber', 'TEXT'),
# ('Area', 'area', 'TEXT'),
# ('Level', 'level', 'TEXT'),

object_types = {

    'bags':
        {'label': 'Bags',
         'input_fields': [
             SEASON,
             ('Recorders', 'recorders', 'TEXT', RECORDERS),
             ('T-Number', 'tnumber', 'TEXT'),
             ('Context', 'context', 'TEXT'),
             ('Excavation Unit', 'excavation_unit', 'TEXT',
              "DROPDOWN('SqA', 'SqC', 'Op1')"),
             ('Area', 'area', 'TEXT'),
             ('Level', 'level', 'TEXT'),
             ('Date recorded', 'date_recorded', 'DATE'),
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
         'result_rows': [
             ['recorders'],
             ['season', 'tnumber'],
             ['excavation_unit', 'area', 'level'],
             ['context', 'date_recorded'],
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
        {'label': 'Artifacts',
         'input_fields': [
             ('Recorders', 'recorders', 'TEXT', RECORDERS),
             SEASON,
             ('T-Number', 'tnumber', 'TEXT'),
             ('Context', 'context', 'TEXT'),
             ('Excavation Unit', 'excavation_unit', 'TEXT',
              "DROPDOWN('SqA', 'SqC', 'Op1')"),
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
             ['season'],
             ['context'],
             ['tnumber'],
             ['excavation_date'],
             ['surface_treatment'],
             ['temper'],
             ['typology_number'],
             # ['munsell_color'],
             ['collar_height'],
             ['rim_diameter'],
             ['notes'],
         ],
         'result_rows': [
             ['recorders'],
             ['season', 'tnumber'],
             ['excavation_unit', 'area', 'level'],
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
             'season',
             'tnumber',
             'context',
             'excavation_date',
         )
         },

    'photographs':
        {'label': 'Photographs',
         'input_fields': [
             ('Photographer', 'photographer', 'TEXT', RECORDERS),
             SEASON,
             ('Site Name', 'site_name', 'TEXT'),
             ('Shot type', 'shot_type', 'TEXT'),
             ('Date recorded', 'date_recorded', 'TIMESTAMP'),
         ],
         'layout_rows': [
             ['photographer'],
             ['season'],
             ['site_name'],
             ['comments'],
             ['date_recorded'],
         ],
         'required_fields': (
             'photographer',
             'season',
             'site_name',
             'shot_type',
         )
         },
}
