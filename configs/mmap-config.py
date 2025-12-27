# config.py
# MMAP configuration for the Artifact Capture app.
#
# object_types defines the metadata schema and layout per object type.
# Each field tuple is:
#   (label, column_name, sql_type[, widget])
#
# widget is optional; for dropdowns use:
#   'DROPDOWN('Option 1', 'Option 2')'
#
# Banner / UI config:

APP_BRAND = 'MMAP'
APP_SUBTITLE = ''  # optional, shown smaller in the banner
APP_LOGO = 'mmap-logo-pot-and-river-small.png'
SHOW_LOGO = True  # displays logo
ADMIN_LABEL = 'Admin'  # label used in admin page titles
FILENAME_PREFIX = 'MMAP'  # prefix used for generated filenames

BANNER_BG = '#f9d88d'  # navbar background
BANNER_FG = '#000000'  # navbar text
BANNER_ACCENT = '#60a5fa'  # active link underline/accent

GPS_ENABLED = True

object_types = {

    'photograps':
        {'label': 'Photographs',
         'input_fields': [
             ('Photographer', 'photographer', 'TEXT',
              'DROPDOWN("joyce", "elizabeth", "suliya", "nitaxay", "pengborn", "jb", "other")'),
             ('Site Name', 'site_name', 'TEXT'),
             ('Shot type', 'shot_type', 'TEXT',
              'DROPDOWN( "general view", "feature at site", "environment", "artifacts", "miscellaneous", "action/process", "studio bag", "studio artifact", "people at site", "lab views")'),
             ('Comments', 'comments', 'TEXT'),
             ('Date recorded', 'date_recorded', 'TIMESTAMP'),
         ],
         'layout_rows': [
             ['photographer'],
             ['site_name'],
             ['shot_type'],
             ['comments'],
             ['date_recorded'],
         ],
         'required_fields': (
             'photographer',
             'site_name',
             'shot_type',
         )
         },

    'artifacts':
        {'label': 'Artifacts',
         'input_fields': [
             ('Recorders', 'recorders', 'TEXT',
              'DROPDOWN("jw", "eh", "jbl", "xx")'),
             ('Artifact ID', 'mmap_artifact_id', 'TEXT'),
             ('Site Name', 'site_name', 'TEXT'),
             ('Date Discovered', 'date_discovered', 'TEXT'),
             ('Bag ID', 'bag_id', 'TEXT'),
             ('Artifact Class', 'artifact_class', 'TEXT',
              'DROPDOWN( "Flake", "Bangle", "Bead", "Core", "Cylinder/roller", "Metal amorphous", "Miscellaneous clay", "Miscellaneous stone", "Pellet", "Pestle", "Pot", "Sherd", "Worked bone")'),
             ('Maximum Dimension', 'maximum_dimension', 'TEXT'),
             ('Weight', 'weight', 'TEXT'),
             ('Count', 'count', 'TEXT'),
             ('Burial No', 'burial_no', 'TEXT'),
             ('Period', 'period', 'TEXT'),
             ('Material', 'material', 'TEXT'),
             ('Comments', 'comments', 'TEXT'),
             ('Bur Phase', 'bur_phase', 'TEXT'),
             ('Level', 'level', 'TEXT'),
             ('Square', 'square', 'TEXT'),
             ('Quad', 'quad', 'TEXT'),
             ('Layer', 'layer', 'TEXT'),
             ('Feano', 'feano', 'TEXT'),
             ('Notes', 'notes', 'TEXT'),
         ],
         'layout_rows': [
             ['recorders'],
             ['mmap_artifact_id'],
             ['artifact_class'],
             ['site_name'],
             ['bag_id'],
             ['material'],
             ['maximum_dimension'],
             ['weight'],
             ['level'],
             ['square'],
             ['quad'],
             ['layer'],
             ['feano'],
             ['notes'],
         ],
         'required_fields': (
             'mmap_artifact_id',
             'artifact_class',
             'site_name',
             'bag_id',
         )
         },

    'sites':
        {'label': 'Sites',
         'input_fields': [
             ('Date recorded', 'date_recorded', 'TIMESTAMP'),
             ('Site name', 'site_name', 'TEXT'),
             ('Village', 'village', 'TEXT'),
             ('Description', 'description', 'TEXT'),
             ('Nearest river', 'nearest_river', 'TEXT'),
             ('Size', 'size', 'TEXT'),
             ('Priority', 'priority', 'TEXT', 'DROPDOWN("High", "Medium", "Low")'),
             ('Notes', 'notes', 'TEXT'),
         ],
         'layout_rows': [
             ['date_recorded'],
             ['site_name'],
             ['village'],
             ['description'],
             ['nearest_river'],
             ['size'],
             ['priority'],
             ['notes'],
         ],
         'required_fields': (
             'village',
             'description',
             'site_name',
         )
         }
}
