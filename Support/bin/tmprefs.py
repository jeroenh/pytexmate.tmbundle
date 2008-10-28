import os
import newplistlib as plistlib

# NIB constants:
# latexTypesetAction radio buttons
typesetActionLatex   = 0
typesetActionMake    = 1
typesetActionLatexmk = 2

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
            'latexKeepLogWin' : 1
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
        # "defaults read com.macromates.textmate latexVerbose" does this, but can't distinguish between 1 and True.
        plDict = {}
        os.system("plutil -convert xml1 $HOME/Library/Preferences/com.macromates.textmate.plist -o /tmp/tmltxprefs1.plist")
        os.system(" cat /tmp/tmltxprefs1.plist | tr -d '\\000'-'\\011''\\013''\\014''\\016'-'\\037''\\200'-'\\377' > /tmp/tmltxprefs.plist" )
        pl = open('/tmp/tmltxprefs.plist')
        try:
            plDict = plistlib.readPlist(pl)
        except:
            print '<p class="error">There was a problem reading the preferences file, continuing with defaults</p>'
        pl.close()
        try:
            os.remove("/tmp/tmltxprefs.plist")
            os.remove("/tmp/tmltxprefs1.plist")
        except:
            print '<p class="error">Problem removing temporary prefs file</p>'
        #keys = ['latexAutoView', 'latexEngine', 'latexEngineOptions', 'latexUselatexmk', 'latexViewer']
        #for key in keys:
        #    value = self.readTMPref(key)
        #    if value != None:
        #        plDict[key] = value
        return plDict
    
    def readTMPref(self, key):
        domain = "com.macromates.textmate"
        stdin,stdout = os.popen2('defaults read %s "%s"' % (domain, key))
        value = stdout.read()
        stdin.close()
        stdout.close()
        if value == "":
            value = None
        return value
    
    def extractLatexPrefs(self):
        """plist-formated string with preference values"""
        prefs = {}
        for key, value in self.prefs.iteritems():
            if key.startswith("latex"):
                prefs[key] = value
        return prefs

    def toDefString(self):
        """plist-formated string with default values"""
        instr = plistlib.writePlistToString(self.defaults)
        stdin,stdout = os.popen2('pl')
        stdin.write(instr)
        stdin.close()
        defstr = stdout.read()
        return defstr.replace("\n","")

if __name__ == '__main__':
    test = Preferences()
    print "Preferences =", test.prefs
    print "Defaults (plist) =", repr(test.toDefString())
    
    
