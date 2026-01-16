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
          "DROPDOWN('TAP86', 'TAP90', 'TAP92', 'TAP94')")
CONTEXT = ('Context e.g. X,□,○', 'context', 'TEXT')
EX_UNIT = ('Excavation Unit', 'excavation_unit', 'TEXT', "DROPDOWN('SqA', 'SqC', 'Op1')")
AREA = ('Area', 'area', 'TEXT')
LEVEL = ('Level', 'level', 'TEXT')
EX_DATE = ('Excavation Date', 'excavation_date', 'DATE')
#TREATMENT = ('Surface Treatment', 'surface_treatment', 'TEXT',
# "DROPDOWN('red slip',  'black slip',  'cord marking',  'cross-hatch incising',  'interior red slip',  'exterior red slip',  'both sides red slip',  'parallel incised',  'other incised',  'multiple (incising, cord)')"),
TREATMENT = ('Surface Treatment', 'surface_treatment', 'TEXT')

# ('Excavation Unit', 'excavation_unit', 'TEXT',
#  # 'DROPDOWN('Op1', 'Op2', 'Op3', 'Op4', 'Op5', 'Op6', 'Op7', 'Op8', 'Op9', 'Op10', 'SqA', 'SqB', 'SqC')'),
#  "DROPDOWN('SqA', 'SqC', 'Op1')"),
# ('T-Number', 'tnumber', 'TEXT'),
# ('Area', 'area', 'TEXT'),
# ('Level', 'level', 'TEXT'),

object_types = {

    'bags':
        {'label': 'Bags',
         'filename_format': 'BAG_{season}_Unit{unit}_T{tnum}_Lot_{lot}_Area{area}_Level_{level}_ID{record_id}',
         'input_fields': [
             ('Recorders', 'recorders', 'TEXT', RECORDERS),
             ('T-Number', 'tnumber', 'TEXT'),
             SEASON, CONTEXT, EX_UNIT, AREA, LEVEL, EX_DATE,
             ('Date recorded', 'date_recorded', 'DATE'),
             ('Notes', 'notes', 'TEXT'),
         ],
         'layout_rows': [
             ['recorders'],
             ['season'],
             ['tnumber'],
             ['context'],
             ['excavation_date'],
             ['date_recorded'],
             ['notes'],
         ],
         'result_rows': [
             ['recorders'],
             ['season', 'tnumber'],
             ['excavation_unit', 'area', 'level'],
             ['context', 'excavation_date', 'date_recorded'],
             ['notes'],
         ],
         'required_fields': (
             'season',
             'excavation_unit',
             'area',
             'level',
             'tnumber',
             'context',
         )
         },

    'artifacts':
        {'label': 'Artifacts',
         'filename_format': 'ART_{season}_Unit{unit}_T{tnum}_Lot_{lot}_Area{area}_Level_{level}_ID{record_id}',
         'input_fields': [
             ('Recorders', 'recorders', 'TEXT', RECORDERS),
             ('T-Number', 'tnumber', 'TEXT'),
             SEASON, CONTEXT, EX_UNIT, AREA, LEVEL, EX_DATE,
             ('Vessel Type', 'vessel_type', 'TEXT',
              "DROPDOWN('hole-mouthed jar', 'open-mouthed jar', 'collared jar')"),
             ('Temper', 'temper', 'TEXT',
              "DROPDOWN('T1', 'T2', 'T3','T4', 'T5', 'T6', 'T7')"),
             ('Typology Number', 'typology_number', 'INT'),
             ('Collar Height', 'collar_height', 'FLOAT'),
             ('Rim Diameter', 'rim_diameter', 'FLOAT'),
             TREATMENT,
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
             'excavation_unit',
             'area',
             'level',
             'tnumber',
             'context',
         )
         },

    'photographs':
        {'label': 'Photographs',
         'filename_format': 'PHOTO_{site_name}_ID{record_id}',
         'input_fields': [
             ('Photographer', 'photographer', 'TEXT', RECORDERS),
             SEASON, CONTEXT, EX_UNIT, AREA, LEVEL, EX_DATE,
             ('Site Name', 'site_name', 'TEXT'),
             ('Shot type', 'shot_type', 'TEXT'),
             ('Date recorded', 'date_recorded', 'TIMESTAMP'),
         ],
         'layout_rows': [
             ['photographer'],
             ['season', 'tnumber'],
             ['excavation_unit', 'area', 'level'],
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
