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
GRID_MAX_WIDTH = 500

BANNER_BG = '#A51931'  # navbar background
BANNER_FG = '#ffffff'  # navbar text
BANNER_ACCENT = '#60a5fa'  # active link underline/accent
SHOW_LOGO = True  # looks for static/images/logo.svg

RECORDERS = "RADIO('JB', 'Karen', 'Maprang', 'Nick', 'Non', 'Phai', 'Susan', 'Toey', 'Vince')"
SEASON = ('Season', 'season', 'TEXT',
          "DROPDOWN('TAP86', 'TAP90', 'TAP92', 'TAP94')")
CONTEXT = ('Context e.g. X,□,○', 'context', 'UPPERCASE')
EX_UNIT = ('Excavation Unit', 'excavation_unit', 'TEXT', "DROPDOWN('SqA', 'SqC', 'Op1')")
AREA = ('Area', 'area', 'UPPERCASE')
LEVEL = ('Level', 'level', 'UPPERCASE')
EX_DATE = ('Excavation Date', 'excavation_date', 'DATE')
#TREATMENT = ('Surface Treatment', 'surface_treatment', 'UPPERCASE',
# "DROPDOWN('red slip',  'black slip',  'cord marking',  'cross-hatch incising',  'interior red slip',  'exterior red slip',  'both sides red slip',  'parallel incised',  'other incised',  'multiple (incising, cord)')"),
TREATMENT = ('Surface Treatment', 'surface_treatment', 'UPPERCASE')

# ('Excavation Unit', 'excavation_unit', 'TEXT',
#  # 'DROPDOWN('Op1', 'Op2', 'Op3', 'Op4', 'Op5', 'Op6', 'Op7', 'Op8', 'Op9', 'Op10', 'SqA', 'SqB', 'SqC')'),
#  "DROPDOWN('SqA', 'SqC', 'Op1')"),
# ('T-Number', 'tnumber', 'TEXT'),
# ('Area', 'area', 'TEXT'),
# ('Level', 'level', 'TEXT'),

object_types = {

    'bags':
        {'label': 'Bags',
         'filename_format': 'BAG_{season}_Unit{excavation_unit}_T{tnumber}_Lot_{lot}_Area{area}_Level_{level}_ID{record_id}',
         'fields_to_reset': ['context', 'tnumber', 'excavation_date', 'notes'],
         'copy_from': 'artifacts',
         'index': ['tnumber', 'context', 'excavation_date'],
         'result_grid': ['tnumber', 'context'],
         'input_fields': [
             ('Recorder(s)', 'recorders', 'TEXT', RECORDERS),
             ('T-Number', 'tnumber', 'TEXT'),
             SEASON, CONTEXT, EX_UNIT, AREA, LEVEL, EX_DATE,
             ('Date recorded', 'date_recorded', 'DATE'),
             ('Date updated', 'date_updated', 'TIMESTAMP'),
             ('Notes', 'notes', 'TEXT'),
         ],
         'layout_rows': [
             ['recorders'],
             ['season'],
             ['tnumber'],
             ['context'],
             ['excavation_date'],
             # ['date_recorded'],
             ['notes'],
         ],
         'result_rows': [
             ['recorders'],
             ['tnumber', 'context', 'excavation_date'],
             ['date_recorded', 'date_updated'],
             #['season', 'tnumber'],
             # ['excavation_unit', 'area', 'level'],
             #['context', 'excavation_date', 'date_recorded'],
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
         'filename_format': 'ART_{season}_Unit{excavation_unit}_T{tnumber}_Lot_{lot}_Area{area}_Level_{level}_ID{record_id}',
         'fields_to_reset': ['temper', 'typology_number', 'collar_height', 'rim_diameter', 'surface_treatment', 'notes'],
         'index': ['surface_treatment', 'typology_number', 'temper', 'context', 'vessel_type'],
         'result_grid': ['tnumber', 'context'],
         'copy_from': 'bags',
         'input_fields': [
             ('Recorder(s)', 'recorders', 'TEXT', RECORDERS),
             ('T-Number', 'tnumber', 'TEXT'),
             SEASON, CONTEXT, EX_UNIT, AREA, LEVEL, EX_DATE,
             ('Vessel Type', 'vessel_type', 'UPPERCASE',
              "DROPDOWN('hole-mouthed jar', 'open-mouthed jar', 'collared jar')"),
             ('Temper', 'temper', 'TEXT',
              "DROPDOWN('1', '2', '3','4', '5a', '5b', '6', '7')"),
             ('Typology Number', 'typology_number', 'INT'),
             ('Collar Height', 'collar_height', 'FLOAT'),
             ('Rim Diameter', 'rim_diameter', 'FLOAT'),
             TREATMENT,
             ('Notes', 'notes', 'TEXT'),
             ('Date recorded', 'date_recorded', 'DATE'),
             ('Date updated', 'date_updated', 'TIMESTAMP'),
         ],
         'layout_rows': [
             ['recorders'],
             ['season'],
             ['context'],
             ['tnumber'],
             ['excavation_date'],
             ['typology_number'],
             ['surface_treatment'],
             ['rim_diameter'],
             ['collar_height'],
             ['temper'],
             ['notes'],
             # ['munsell_color'],
         ],
         'result_rows': [
             ['recorders'],
             ['tnumber', 'context', 'excavation_date'],
             ['date_recorded', 'date_updated'],
             #['season', 'tnumber'],
             # ['excavation_unit', 'area', 'level'],
             #['context', 'excavation_date', 'date_recorded'],
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
         'filename_format': 'PHOTO_{site_name}_{shot_type}ID{record_id}',
         'fields_to_reset': [],
         'result_grid': ['photographer', 'shot_type'],
         'input_fields': [
             ('Photographer', 'photographer', 'TEXT', RECORDERS),
             SEASON, CONTEXT, EX_UNIT, AREA, LEVEL, EX_DATE,
             ('Site Name', 'site_name', 'UPPERCASE'),
             ('Shot type', 'shot_type', 'TEXT'),
             ('Date recorded', 'date_recorded', 'DATE'),
             ('Date updated', 'date_updated', 'TIMESTAMP'),
         ],
         'layout_rows': [
             ['photographer'],
             ['season'],
             ['site_name'],
             ['context'],
             ['comments'],
             ['date_recorded'],
         ],
         'result_rows': [
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
