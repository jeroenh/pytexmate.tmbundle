#!/usr/bin/python

import os
import tmprefs
import subprocess
pref = tmprefs.Preferences()
defaults = '-d ' + "'" + pref.toDefString() + "' "
command = '"$DIALOG"' + ' -mp "" ' + defaults + '"$TM_BUNDLE_SUPPORT"'+"/nibs/tex_prefs.nib"
p = subprocess.Popen(command, shell=True,
          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True)
sin = p.stdin
result = p.stdout
