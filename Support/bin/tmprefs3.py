from __future__ import unicode_literals
try: 
    str = unicode 
except NameError: 
    pass 

import os
import newplistlib as plistlib
#import plistlib
import io
import string


# NIB constants:
# latexTypesetAction radio buttons
typesetActionLatex   = 0
typesetActionMake    = 1
typesetActionLatexmk = 2

try:
    import Foundation
    haspyobjc = True
except:
    haspyobjc = False


try:
    from subprocess import Popen, PIPE, STDOUT
except:
    PIPE = 1
    STDOUT=1
    class Popen(object):
        """Popen:  This class provides backward compatibility for Tiger
           Do not assume anything about this works other than access
           to stdin, stdout and the wait method."""
        def __init__(self, command, **kwargs):
            super(Popen, self).__init__()
            self.command = command
            self.stdin, self.stdout = os.popen4(command)

        def wait(self):
            stat = self.stdout.close()
            return stat

class Preferences(object):
    """docstring for Preferences"""
    def __init__(self):
        super(Preferences, self).__init__()
        self.defaults = {
            'latexAutoView' : 1, 
            'latexEngine' : "pdflatex",
            'latexEngineOptions' : "",
            'latexVerbose' : 0,
            'latexTypesetAction': typesetActionLatex,
            'latexUselatexmk' : 0,
            'latexViewer' : "TextMate",
            'latexKeepLogWin' : 1,
            'latexDebug' : 0,
        }
        self.prefs = self.readPrefs()
        
    def __getitem__(self,key):
        """docstring for __getitem__"""
        return self.prefs.get(key,None)

    def readPrefs(self):
        """Read preferences from file, and set self.prefs. If a key if not defined (or empty!),
        replace it with the defaul value"""
        tmprefs = self.readTMPrefs()
        # set custom default for latexTypesetAction if old key latexUselatexmk is still defined.
        if "latexTypesetAction" not in tmprefs and "latexUselatexmk" in tmprefs:
            if tmprefs["latexUselatexmk"]:
                self.defaults["latexTypesetAction"] = typesetActionLatexmk
            else:
                self.defaults["latexTypesetAction"] = typesetActionLatex
        prefs = {}
        # We don't use self.prefs.update(prefs), so we only keep the latex-defined prefs on record.
        for key in self.defaults:
            if key in tmprefs:
                prefs[key] = tmprefs[key]
            else:
                prefs[key] = self.defaults[key]
        return prefs
    
    def readTMPrefs(self):
        """readTMPrefs reads the textmate preferences file and constructs a python dictionary.
        The keys that are important for latex are as follows:
        latexAutoView = 0
        latexEngine = pdflatex
        latexEngineOptions = "-interaction=nonstopmode -file-line-error-style"
        latexUselatexmk = 0
        latexViewer = Skim
        """
        # ugly as this is it is the only way I have found so far to convert a binary plist file into something
        # decent in Python without requiring the PyObjC module.  I would prefer to use popen but
        # plutil apparently tries to do something to /dev/stdout which causes an error message to be appended
        # to the output.
        #
        plDict = {}
        if haspyobjc:
            plDict = Foundation.NSDictionary.dictionaryWithContentsOfFile_(os.environ["HOME"]+"/Library/Preferences/com.macromates.textmate.plist")
        else:   # TODO remove all this once everyone is on leopard
            os.system("plutil -convert xml1 \"$HOME/Library/Preferences/com.macromates.textmate.plist\" -o /tmp/tmltxprefs1.plist")
            plist_str = open('/tmp/tmltxprefs1.plist', 'rt').read()
            try:
                # python 2
                null_tt = "".join([chr(i) for i in range(256)])
                non_printables = null_tt.translate(null_tt, string.printable)
                plist_str = plist_str.translate(null_tt,non_printables)
            except TypeError:
                # python 3
                non_printables = [chr(i) for i in range(256) if chr(i) not in string.printable]
                null_tt = dict(zip(non_printables, len(non_printables)*[None]))
                plist_str = plist_str.translate(null_tt)
            try:
                # wrapper around string to make it a file object
                plDict = plistlib.readPlistFromString(plist_str.encode('utf-8')) 
            except ZeroDivisionError:
                print('<p class="error">There was a problem reading the preferences file, continuing with defaults</p>')
            try:
                os.remove("/tmp/tmltxprefs1.plist")
            except:
                print('<p class="error">Problem removing temporary prefs file</p>')
        return plDict
        
    def toDefString(self):
        """plist-formated string with preference values"""
        # instr = plistlib.writePlistToString(self.defaults)
        instr = plistlib.writePlistToString(self.defaults)
        runObj = Popen('pl',shell=True,stdout=PIPE,stdin=PIPE,stderr=STDOUT,close_fds=True)
        runObj.stdin.write(instr) # .encode("utf-8"))
        runObj.stdin.close()
        defstr = runObj.stdout.read()
        defstr = defstr.decode("utf-8")
        return defstr.replace("\n","")

if __name__ == '__main__':
    test = Preferences()
    print("Preferences =", test.prefs)
    print("Defaults (plist) =", repr(test.toDefString()))
    

