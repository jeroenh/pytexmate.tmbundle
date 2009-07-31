#!/usr/bin/env python
# encoding: utf-8

# This is a rewrite of latexErrWarn.py
# Goals:
#   1.  Modularize the processing of a latex run to better capture and parse errors
#   2.  replace latexmk
#   3.  provide a nice pushbutton interface for manually running latex,bibtex,mkindex, and viewing
#   
# Overview:
#    Each tex command has its own class that parses the output from that program.  Each of these classes
#    extends the TexParser class which provides default methods:
#       parseStream
#       error
#       warning
#       info
#   The parseStream method reads each line from the input stream matches against a set of regular
#   expressions defined in the patterns dictionary.  If one of these patterns matches then the 
#   corresponding method is called.  This method is also stored in the dictionary.  Pattern matching
#   callback methods must each take the match object as well as the current line as a parameter.
#
#   Progress:
#       7/17/07  -- Brad Miller
#       Implemented  TexParse, BibTexParser, and LaTexParser classes
#       see the TODO's sprinkled in the code below
#       7/24/07  -- Brad Miller
#       Spiffy new configuration window added
#       pushbutton interface at the end of the latex output is added
#       the confusing mass of code that was Typeset & View has been replaced by this one
#
#   Future:
# 
#       think about replacing latexmk.pl with a simpler python version.  If only rubber worked reliably..
#       Rubber: http://www.pps.jussieu.fr/~beffara/soft/rubber/
#

from __future__ import unicode_literals
try: 
    str = unicode 
except NameError: 
    pass 

import sys
import re
import os
import os.path
import tmprefs
try:
    from urllib.parse import quote  # python 3
except ImportError:
    from urllib import quote  # python 2
from xml.sax.saxutils import escape
from struct import *
from texparser import *


###############################################################
#                                                             #
#         Helper functions for running subprocesses           #
#                                                             #
###############################################################

def shell_quote(string):
    """Add a backslash (\) before \, $ and " characters, so the string can be used in a shell. """
    return '"' + re.sub(r'([`$\\"])', r'\\\1', string) + '"'

def argumentStrToList(argumentline):
    """Convert a string of arguments to an array, removing quotes (single and double), and take 
    backslashes into account. The goal is to mimmic the behaviour of the shell as closely as possible."""
    arguments = []
    # special chars:
    delimiter = [" ", "\t", "\n", "\r", "\u000B", "\u000C", "\u0085", "\u0029", "\u0029"]
    quotes = ["'", '"']
    curarg = ""
    prevch = ""
    quote  = ""
    for ch in argumentline:
        if prevch == "\\":
            if not (ch == quote or ch in delimiter):
                curarg += "\\"  # interpret backslash literaly; only spaces and quotes may be quoted.
            curarg += ch
        elif ch == quote: # end of quote
            quote = ""
            # do not yet add curarg to arguments, "word1"word2 is parsed as word1word2 (one argument)
        elif ch == "\\":
            pass
        elif quote != "":
            curarg += ch
        elif ch in delimiter:
            if len(curarg) > 0:
                arguments.append(curarg)
            curarg = ""
            hasarg = False
        elif ch in quotes:
            quote = ch
        else:
            curarg += ch
        prevch = ch
    if curarg != "":
        arguments.append(curarg)
    if quote != "":
        # warning! uneven number of quotes
        pass
    return arguments

def parseOptions(argumentArray):
    """Given an array of arguments (as returned by argumentStrToList), 
    return a dict of options and an array of positional arguments."""
    # We don't use getopt or optparse, since we want to be able to parse any option.
    # Thankfully, all latex variants use full-words for options with - or --. Eg.:
    # -output-directory directory       -> output-directory: directory
    # -halt-on-error                    -> halt-on-error: None
    # --result="FILENAME"               -> result: FILENAME
    curoption=None
    options = {}
    arguments = []
    for argument in argumentArray:
        if argument[0] == "-":
            curoption = argument.lstrip('-')
            if "=" in curoption:    # option in one argument, e.g. ["--option=value"]
                curoption, value = curoption.split('=',1)
                options[curoption] = value
                curoption = None
            else:                   # option without value, e.g. ["--option"]
                options[curoption] = None
        elif curoption != None:     # option in two arguments, e.g. ["--option", "value"]
            options[curoption] = argument
            curoption = None
        else:                       # positional argument, e.g. ["argument"]
            arguments.append(curoption)
    return options, arguments


def runProcess(popenargs):
    """
    Run program and return the result code. spaces and quotes in program and arguments should NOT be escaped.
    If the program is not found, or was killed, print an error and return -signalcode.
    popenargs is a list of program and arguments. E.g. ["open", "-a", "PDFviers.app", "file.pdf"]
    """
    # Note that we can't use subprocess.call(), since that is only available for Python 2.4 and up (=Mac OS X.5 and up)
    #print "<pre>%s%s</pre>" % (popenargs[0], "".join(' "%s"' % arg for arg in popenargs[1:]))  ## DEBUG
    result = ProcessResult()
    result.exitcode = os.spawnvp(os.P_WAIT, popenargs[0], popenargs)
    result.numRuns = 1
    if result.exitcode < 0:
        result.signalcode = -result.exitcode
        result.exitcode = 0
        print("<p class='error'>%s killed by signal %d</p>" % (escape(popenargs[0]), result.signalcode))
    elif result.exitcode == 127:
        print("<p class='error'>Program %s was not found in the current PATH</p>" % (escape(popenargs[0])))
        result.numErrs += 1
    return result

def runOutputProcess(popenargs):
    """
    Run program and return stdout. popenargs is a list of program and arguments.
    If the program is not found, was killed, or returns a non-zero result code, 
    print an error and return an empty string. To avoid locking, stderr is ignored.
    """
    # Note that we can't use subprocess.Popen(), since that is only available for Python 2.4 and up (=Mac OS X.5 and up)
    command = " ".join(shell_quote(arg) for arg in popenargs)  # quote everything, even the program path
    #print "<pre>%s</pre>" % command  ## DEBUG
    stdout = os.popen(command, "r")
    return stdout.read()

class ProcessResult(object):
    def __init__(self):
        self.exitcode   = None
        self.signalcode = None
        self.numErrs    = 0
        self.numWarns   = 0
        self.numRuns    = 0
        self.isFatal    = False

def runParsedProcess(popenargs, parser=None):
    """Run a program, and parse the output through a TexParser instance.
    Returns a ProcessResult object with result code, or if the program is not found, or was killed, 
    the signalcode.
    This numRuns, and error and warning counters are increased, as given by the parser instance.
    popenargs is a list of program and arguments. E.g. ["pdflatex", "document.tex"]
    """
    # start program, with popen, create parser and pass stdout+stderr to the parser
    # if the parser is done, 
    # modify numRuns, error, warnings, fatal errors, etc. count
    # return result code
    command = " ".join(shell_quote(arg) for arg in popenargs)  # quote everything, even the program path
    # we use os.popen with stderr piped to stdout, and not os.popen4. The reason is that popen returns the 
    # result code, while popen4 does not.
    command += " 2>&1"
    #print "<pre>%s</pre>" % command  ## DEBUG
    stdout = os.popen(command)
    result = ProcessResult()
    if parser:  # parser is a TexParser instance
        parser.setInput(stdout)  # the output of the subprocess is input for the parser.
        result.isFatal,result.numErrs,result.numWarns = parser.parseStream()
        result.numRuns  = parser.numRuns
    else:
        result.isFatal,result.numErrs,result.numWarns = (False, 0, 0)
        result.numRuns  = 1
    resultcode = stdout.close()  # Note: this only works for popen, not for popen4.
    if resultcode == None:       # the resultcode is NOT guaranteed to return anything at all.
        resultcode = 0
    result.signalcode = (resultcode & 255)
    result.exitcode   = resultcode >> 8
    if result.isFatal:
        print("<p class='error'>Fatal error while running %s</p>" % (escape(popenargs[0])))
        result.exitcode = -1
    if result.signalcode > 0:
        print("<p class='error'>%s killed by signal %d</p>" % (escape(popenargs[0]), result.signalcode))
    elif result.exitcode == 127:
        print("<p class='error'>Program %s was not found in the current PATH</p>" % (escape(popenargs[0])))
        result.numErrs += 1
    elif result.exitcode > 0:
        print("<p class='error'>Program %s exited with error code %d</p>" % (escape(popenargs[0]), result.exitcode))
    return result



class TexMate(object):
    """TexMate is the program object. Instantiating it will effectively execute a program.
    init parses the arguments, and calls one of the main functions: run_latex, run_bibtex, 
    run_makeindex, run_view, run_clean, and run_make.
    """
###############################################################
#                                                             #
#            Initialization: read configurations              #
#                                                             #
###############################################################

    def __init__(self, firstRun=True):
        """Initializes program environment: set option values, preferences, read parameters, etc."""
        self.verbose = False
        self.numRuns = 0
        self.stat = 0
        self.texStatus = None
        self.numErrs = 0
        self.numWarns = 0
        self.firstRun = firstRun
        # Get preferences from TextMate and local directives
        self.tmPrefs = tmprefs.Preferences()
        self.keepLogWindow = self.tmPrefs['latexKeepLogWin']      
        self.tsDirs = self.find_TEX_directives()
        if self.tmPrefs['latexVerbose'] == 1:
            self.verbose = True
        #
        # Set up some configuration variables
        #
        
        self.inputfile = self.findFileToTypeset()        # full path, with extension
        self.fileName = os.path.basename(self.inputfile) # relative path of input file
        #print "<pre>Found file to typeset: %s</pre>" % (self.inputfile)
        #print "<pre>Variables: TM_FILEPATH=%s, TM_LINE_NUMBER=%s, TM_BUNDLE_SUPPORT=%s, TM_LATEX_MASTER=%s, TEXINPUTS=%s</pre>" % (os.getenv('TM_FILEPATH'), os.getenv('TM_LINE_NUMBER'), os.getenv('TM_BUNDLE_SUPPORT'), os.getenv('TM_LATEX_MASTER'), os.getenv('TEXINPUTS'), )
        #print "<pre>Preferences: %s</pre>" % ["%s: %s" % (pref,self.tmPrefs.prefs[pref]) for pref in self.tmPrefs.prefs if pref.startswith('latex')]
        
        self.setEnvironment()
        self.ltxIncludes, self.ltxPackages = self.findTexPackages(self.fileName)
        #print "<pre>includes = %s</pre>" % self.ltxIncludes
        #print "<pre>packages = %s</pre>" % self.ltxPackages
        self.viewer = self.tmPrefs['latexViewer']
        self.engine = self.constructEngineCommand()
        if os.system(self.engine + " --help |grep -q synctex") == 0:
            self.syncTexSupport = True
        else:
            self.syncTexSupport = False
        self.engineoptions = argumentStrToList(self.constructEngineOptions())
        self.outputNoSuffix = self.findOutputFile() # output file with relative path, without extension
        self.outputdir = os.path.dirname(self.outputNoSuffix)
        self.outputfile = os.path.realpath(os.path.join(os.path.dirname(self.inputfile), self.outputNoSuffix))     # output file with full path, without extension
        #print "<pre>outputNoSuffix = %s</pre>" % self.outputNoSuffix
        #print "<pre>outputfile = %s</pre>" % self.outputfile
    
    def findFileToTypeset(self):
        """determine which file to typeset.  Using the following rules:
           + %!TEX root directive
           + using the TM_LATEX_MASTER environment variable
           + Using TM_FILEPATH
           Once the file is decided return the name of the file and the normalized absolute path to the
           file as a tuple.
        """
        if 'root' in self.tsDirs:
            f = self.tsDirs['root']
        elif os.getenv('TM_LATEX_MASTER'):
            f = os.getenv('TM_LATEX_MASTER')
        else:
            f = os.getenv('TM_FILEPATH')
        texfile = os.getenv('TM_FILEPATH')
        startDir = os.path.dirname(texfile)
        filename = os.path.realpath(os.path.join(startDir, f))  # os.path.join also works fine if f is an absolute path.
        if not os.path.exists(filename):
            print('<p class="error">Error: Input file %s does not exist</p>' % escape(f))
            print('<p class="error">This is most likely a problem with TM_LATEX_MASTER</p>')
            sys.exit(66) # EX_NOINPUT
        return filename
    
    def find_TEX_directives(self):
        """build a dictionary of %!TEX directives
           the main ones we are concerned with are
           root : which specifies a root file to run tex on for this subsidiary
           TS-program : which tells us which latex program to run
           TS-options : options to pass to TS-program
           encoding  :  file encoding
        """
        texfile = os.getenv('TM_FILEPATH')
        startDir = os.path.dirname(texfile)
        done = False    
        tsDirectives = {}
        rootChain = [texfile]
        while not done:
            try:
                f = open(texfile)
                foundNewRoot = False
                for i in range(20): # read first 20 lines
                    line = f.readline()
                    m =  re.match(r'^%!TEX\s+([\w-]+)\s*=\s*(.*)',line)
                    if m:
                        if m.group(1) == 'root':
                            foundNewRoot = True
                            newtf = os.path.realpath(os.path.join(startDir,m.group(2).rstrip()))
                            if newtf in rootChain:
                                print("<p class='error'> There is a loop in your '%!TEX root =' directives.</p>")
                                print("<p class='error'> chain = ",rootChain, "</p>")
                                print("<p class='error'> exiting.</p>")                        
                                sys.exit(65) # EX_DATAERR
                            else:
                                texfile = newtf
                                rootChain.append(newtf)
                            startDir = os.path.dirname(texfile)
                            tsDirectives['root'] = texfile
                        else:
                            tsDirectives[m.group(1)] = m.group(2).rstrip()
            except (IOError, OSError) as e:
                print("<p class='error'>Can not open root file %s.</p>" % escape(texfile))
                sys.exit(66) # EX_NOINPUT
            f.close()
            if foundNewRoot == False:
                done = True
        
        return tsDirectives
    
    def findTexPackages(self,fileName):
        """Find all packages included by the master file.
           or any file included from the master.  We should not have to go
           more than one level deep for preamble stuff.
        """
        unprocessedFiles = [fileName]
        processedFiles = []
        includeList = set([])
        packageList = set([])
        while len(unprocessedFiles) > 0:
            fileName = unprocessedFiles.pop()
            processedFiles.append(fileName)
            moreIncludes, morePackage = self.findIncludes(fileName, unprocessedFiles, processedFiles)
            includeList.update(moreIncludes)
            packageList.update(morePackage)
        return (includeList, packageList)
    
    def findIncludes(self, fileName, unprocessedFiles, processedFiles):
        """Find the packages and input files in the given TeX file.
        arguments: list of unprocessed, and processed files.
        returns tuple (list of include files, list of packages)."""
        includeList = []
        inputList   = []
        packageList = []
        try:
            fp = open(fileName)
            texString = fp.read()
            fp.close()
            includeList = [x[2] for x in re.findall(r'([^%]|^)(\\include)\{([\w /\.\-]+)\}',texString)]
            inputList   = [x[2] for x in re.findall(r'([^%]|^)(\\input)\{([\w /\.\-]+)\}',texString)]
            packageList = [x[2] for x in re.findall(r'([^%]|^)\\usepackage(\[[\w, \-]+\])?\{([\w\-]+)\}',texString)]
        except (IOError, OSError):
            print('<p class="warning">Warning: Could not open %s to check for packages</p>' % fileName)
        for idx, fileName in enumerate(includeList):
            if not fileName.endswith('.tex'):
                includeList[idx] += '.tex'
        for idx, fileName in enumerate(inputList):
            if not fileName.endswith('.tex'):
                inputList[idx] += '.tex'
        for fileName in (includeList + inputList):
            if (fileName not in unprocessedFiles) and (fileName not in processedFiles):
                unprocessedFiles.append(fileName)
        return (includeList, packageList)
    
    def constructEngineCommand(self):
        """This function decides which engine to run using 
           + %!TEX directives from the tex file
           + Preferences
           + or by detecting certain packages
           The default is pdflatex.  But it may be modified
           to be one of
              latex
              xelatex
              texexec  -- although I'm not sure how compatible context is with any of this
        """
        def usesOnePackage(testPack, allPackages):
            """Helper function: check if the given package is used in the latex file."""
            for p in testPack:
                if p in allPackages:
                    return True
            return False
        
        # main routine
        engine = "pdflatex"
        
        latexIndicators = ['pstricks' , 'xyling' , 'pst-asr' , 'OTtablx' , 'epsfig' ]
        xelatexIndicators = ['xunicode', 'fontspec']
        
        if 'TS-program' in self.tsDirs:
            engine = self.tsDirs['TS-program']
        elif usesOnePackage(latexIndicators,self.ltxPackages):
            engine = 'latex'
        elif usesOnePackage(xelatexIndicators,self.ltxPackages):
            engine = 'xelatex'
        else:
            engine = self.tmPrefs['latexEngine']
        stat = os.system('type '+engine+' > /dev/null')
        if stat != 0:
            print('<p class="error">Error: %s is not found, you need to install LaTeX or be sure that your PATH is setup properly.</p>' % engine)
            sys.exit(69) # EX_UNAVAILABLE
        return engine
    
    def findOutputFile(self):
        """Return the base output file name, without extension. The result is relative to the 
        the input file. By default, this is the basename of the typeset file.
        The output directory can be modified by -output-directory parameter, or TEXMFOUTPUT environment variable."""
        options,arguments = parseOptions(self.engineoptions)  # get %!TEX TS-options and and latexEngineOptions preference.
        outputfile = os.path.splitext(self.inputfile)[0] # by default, the input file, with extension stripped.
        #print "<pre>latex options = %s</pre>" % options
        if 'result' in options:                 # for texexec
            outputfile = options["result"]
        elif 'output-directory' in options:     # for pdflatex and latex
            outputfile = os.path.join(options["output-directory"], os.path.basename(outputfile))
        elif os.getenv('TEXMFOUTPUT'):          
            outputfile = os.path.join(os.getenv('TEXMFOUTPUT'), os.path.basename(outputfile))
        return outputfile
    
    def setEnvironment(self):
        os.chdir(os.path.dirname(self.inputfile))
        # Make sure that the bundle_support/tex directory is added
        if os.getenv('TEXINPUTS'):
            texinputs = os.getenv('TEXINPUTS') + ':'
        else:
            texinputs = ".::"
        texinputs += "%s/tex/" % os.getenv('TM_BUNDLE_SUPPORT')
        os.putenv('TEXINPUTS',texinputs)
        #print "<pre>set TEXTINPUTS=%s</pre>" % texinputs  ## DEBUG
    
###############################################################
#                                                             #
#            Action: process the latex files                  #
#                                                             #
###############################################################

# do_ functions handle global actions (e.g. make, clean, etc.)
# run_ functions spawn exactly one subprocess.
# One action can call multiple run_ functions
# run_ functions return the result code, or kill signal. do_ functions return None.

    def do_action(self, action):
        """Take a high-level action. Action make be one of the following:
        - latex: run latex once, optionally displying the result
        - bibtex: run bibtex once
        - index: run makeindex once
        - view: display the resulting PDF of DVI file
        - make: run latex, bibtex and makeindex multiple times (like latexmk), optionally displying the result
        - clean: remove all nonessential files, including the resuling PDF of DVI file.
        returns a result code. 0 means success.
        """
        if action == "version":
            self.do_version()
        #
        # print out header information to begin the run
        #
        if not self.firstRun:
            print('<hr />')
        print('<div id="commandOutput">')
        print('<div id="preText">')
        if self.fileName == os.path.splitext(self.fileName)[0]:
            print("<h2 class='warning'>Warning:  Latex file has no extension.  See log for errors/warnings</h2>")
        if self.syncTexSupport and 'pdfsync' in self.ltxPackages:
            print("<p class='warning'>Warning:  %s supports synctex but you have included pdfsync. You can safely remove \\usepackage{pdfsync}</p>" % (self.engine))
        
        # Run the command passed on the command line or modified by preferences
        if action == "latex":
            self.do_latex()
        elif action == "bibtex":
            self.do_bibtex()
        elif action == "index":
            self.do_makeindex()
        elif action == "view":
            self.do_view()
        elif action == "make":
            self.do_make()
        elif action == "clean":
            self.do_clean()
        else:
            sys.stderr.write("Unknown action %s\n" % str(action))
            sys.stderr.write("Usage: "+sys.argv[0]+" tex-command firstRun\n")
            return 255
        
        print('</div>')  # closes <div id="preText">
        print('</div>')  # closes <div id="commandOutput"> 
        if self.firstRun:
            # only need to include the javascript library once
            self.printButtons()
        #
        # Decide what to do with the Latex & View log window   
        #
        if (self.numErrs > 0) or (self.numWarns > 0):
            self.keepLogWindow = True
        if self.keepLogWindow:
            return 0
        else:
            return 200
    
    def do_version(self):
        print(runOutputProcess([self.engine, "--version"]).split("\n")[0])
        sys.exit(0)
          
    def do_latex(self):
        """Run latex command, and optionally display the result."""
        if self.tmPrefs['latexTypesetAction'] == tmprefs.typesetActionLatexmk:
            stat = self.run_latexmk()
            print('<p>%d Errors, %d Warnings in %d runs.</p>' % (self.numErrs, self.numWarns, self.numRuns))
            self.view_result()
        elif self.tmPrefs['latexTypesetAction'] == tmprefs.typesetActionMake:
            self.do_make()
            # child takes care of display PDF and printing stats.
        else:  # self.tmPrefs['latexTypesetAction'] == tmprefs.typesetActionLatex:
            stat = self.run_latex()
            print('<p>%d Errors, %d Warnings in %d run.</p>' % (self.numErrs, self.numWarns, self.numRuns))
            self.view_result()
    
    def do_make(self):
        """Run latex, bibtex and makeindex as many times as required to make a correct output file, and optionally display the result."""
        # the latex, bibtex, index, latex, latex sequence should cover 80% of the cases that latexmk does
        stat = self.run_latex()
        if stat != 0:
            return
        self.numErrs, self.numWarns = (0,0) # reset warnings/errors
        # only need to run bibtex if .aux file contains a line "\citation"
        stat = self.do_bibtex()
        if stat != 0:
            return
        if os.path.exists(self.outputNoSuffix+'.idx'):
            stat = self.do_makeindex()
            if stat != 0:
                return
        numErrs, numWarns = (self.numErrs, self.numWarns)  # store warning/error count
        stat = self.run_latex()
        if stat != 0:
            return
        self.numErrs, self.numWarns = (numErrs, numWarns)  # restore warning/error count (only count last run)
        stat = self.run_latex()
        if stat != 0:
            return
        print('<p>%d Errors, %d Warnings after %d runs.</p>' % (self.numErrs, self.numWarns, self.numRuns))
        self.view_result()
    
    def do_bibtex(self):
        """Run bibtex for all source files."""
        print('<h2>Running BibTeX on %s</h2>' % (os.path.basename(self.fileName)))
        if self.outputdir != "" and len(self.ltxIncludes) > 0:
            print('<p class="error">Error: BibTeX can\'t handle a different output directory (%s) in combination with \include{}. Use \input{} or output to the same directory.' % (self.outputdir))
        stat = 0
        # TODO: use smarter .aux find method
        auxfiles = [f for f in os.listdir(os.path.dirname(self.outputfile)) if re.search('.aux$',f) > 0]
        auxfiles = [f for f in auxfiles if re.match(r'('+ os.path.basename(self.outputNoSuffix) +r'.*\.aux|bu\d+\.aux)',f)] # DEBUG : fails if basename if regexp. E.g. "abc-def"
        for bib in auxfiles:
            bib = os.path.join(os.path.dirname(self.outputNoSuffix), bib)
            stat = self.run_bibtex(bib)
            # Meaning of bibtex exit codes:
            # 0 = no problems found
            # 1 = warnings only
            # 2 = error
            # 3 = fatal
            if stat < 0 or stat > 1:
                break
        if len(auxfiles) == 0:
            print('<p class="warning">No .aux files found for BibTeX</p>')
        return stat
    
    def do_makeindex(self):
        """Run makeindex for all source files."""
        stat = 0
        print('<h2>Running MakeIndex on %s</h2>' % (os.path.basename(self.fileName)))
        # TODO: use smarter .idx find method
        try:
            texString = open(self.inputfile).read()
        except (IOError, OSError):
            print('<p class="error">Error: Could not open %s to check for makeindex</p>' % self.inputfile)
            print('<p class="error">This is most likely a problem with TM_LATEX_MASTER</p>')
            sys.exit(66) # EX_NOINPUT
        myList = [x[2] for x in re.findall(r'([^%]|^)\\makeindex(\[([\w]+)\])?',texString) if x[2] ]
        
        idxFile = os.path.basename(self.outputNoSuffix+'.idx')
        myList.append(idxFile)
        for idxFile in myList:
            idxFile = os.path.join(os.path.dirname(self.outputNoSuffix), idxFile)
            stat = self.run_makeindex(idxFile)
            if stat != 0:
                break
        return stat
    
    def view_result(self):
        """Display the resulting PDF of DVI file in a viewer, but only if no errors are present in the stats."""
        if not self.tmPrefs['latexAutoView']:
            return
        if self.numErrs > 0:
            ## print '<p class="error">Not updating viewer. LaTeX reported %d errors.</p>' % self.numErrs
            return
        elif self.viewer != 'TextMate':  # no error
            stat = self.run_external_viewer()
        elif (self.numWarns == 0) or (not self.tmPrefs['latexKeepLogWin']):  # viewer is TextMate
            stat = self.run_texmate_viewer()
        # else: there were warnings and the log window should be kept open: don't replace log with PDF result.
    
    def do_view(self):
        """Display the resulting PDF of DVI file in a viewer."""
        if self.viewer == 'TextMate':
            stat = self.run_texmate_viewer()
        else:
            stat = self.run_external_viewer()
    
    def do_clean(self):
        """Remove all nonessential files, including the resuling PDF or DVI file."""
        if self.tmPrefs['latexTypesetAction'] == tmprefs.typesetActionLatexmk:
            stat = self.run_latexmk_clean()
        else:
            stat = self.run_clean()
    
    def increaseWarningCounts(self, processresult):
        self.numErrs  += processresult.numErrs
        self.numWarns += processresult.numWarns
        self.numRuns  += processresult.numRuns
    
    def run_latex(self):
        """Run the flavor of latex specified by self.engine on self.inputfile"""
        print('<h2>Running %s on %s</h2>' % (self.engine,self.fileName))
        texCommand = [self.engine] + self.engineoptions + [self.fileName]
        commandParser = LaTexParser(None,self.verbose,self.fileName)
        result = runParsedProcess(texCommand, commandParser)
        stat = result.exitcode - result.signalcode
        self.increaseWarningCounts(result)
        if (result.exitcode == 0) and self.engine == 'latex':  # only for latex, if no errors occured
            result = runProcess(['dvips', self.outputNoSuffix+'.dvi', ' -o ', self.outputNoSuffix+'.ps'])
            stat = result.exitcode
            if result.exitcode != 0:
                return result.exitcode
            result = runProcess(['ps2pdf', self.outputNoSuffix+'.ps'])
            stat = result.exitcode
        if commandParser.outputFile and os.path.realpath(commandParser.outputFile) != os.path.realpath(self.outputNoSuffix+'.pdf'):
            print('<p class="warning">Unexpected output file %s. Expected %s. Viewing, BibTeX and MkIndex may fail.</p>' % (commandParser.outputFile, self.outputNoSuffix+'.pdf'))
            self.outputNoSuffix = os.path.splitext(commandParser.outputFile)[0]
            self.outputfile = os.path.join(os.path.dirname(self.inputfile), self.outputNoSuffix)
        return stat
    
    def run_latexmk(self):
        print('<h2>Running latexmk on %s</h2>' % (self.fileName))
        if os.path.splitext(self.inputfile)[0] != self.outputfile:
            print('<p class="error">Error: Latexmk can not handle a different output directory.</p>')
        self.writeLatexmkRc()
        if self.engine == 'latex':
            texCommand = [os.getenv('TM_BUNDLE_SUPPORT') + '/bin/latexmk.pl', '-pdfps', '-f', '-r', '/tmp/latexmkrc', self.fileName]
        else:
            texCommand = [os.getenv('TM_BUNDLE_SUPPORT') + '/bin/latexmk.pl', '-pdf', '-f', '-r', '/tmp/latexmkrc', self.fileName]
        commandParser = ParseLatexMk(None,self.verbose,self.fileName)
        result = runParsedProcess(texCommand, commandParser)
        stat = result.exitcode - result.signalcode
        self.increaseWarningCounts(result)
        try:
            os.remove("/tmp/latexmkrc")
        except (IOError, OSError):
            pass
        return stat
    
    def run_bibtex(self, auxfile):
        """Determine Targets and run bibtex"""
        # print '<h2>Running BibTeX on %s</h2>' % (os.path.basename(auxfile))
        print('<h4>Processing: %s </h4>' % (os.path.basename(auxfile)))
        texCommand = ['bibtex', auxfile]
        commandParser = BibTexParser(None,self.verbose,auxfile)
        result = runParsedProcess(texCommand, commandParser)
        if (result.exitcode == 2) and (result.numErrs == 0):
            # only warnings, most likely about "I found no \citation commands"
            # don't consider this an error.
            result.exitcode = 1
        # LaTeX exit codes:
        # 0 = no problems found
        # 1 = warnings only
        # 2 = error
        # 3 = fatal
        stat = result.exitcode - result.signalcode
        self.increaseWarningCounts(result)
        return stat
    
    def run_makeindex(self, idxfile):
        """Run the makeindex command"""
        # print '<h2>Running MakeIndex on %s</h2>' % (os.path.basename(idxfile))
        print('<h4>Processing: %s </h4>' % (os.path.basename(idxfile)))
        texCommand = ['makeindex', idxfile]
        commandParser = MkIndexParser(None,self.verbose,idxfile)
        result = runParsedProcess(texCommand, commandParser)
        stat = result.exitcode - result.signalcode
        self.increaseWarningCounts(result)
        return stat
    
    def run_latexmk_clean(self):
        """Use latexmk.pl to clean output files"""
        print('<h2>Clean output files of %s</h2>' % (self.fileName))
        texCommand = [os.getenv('TM_BUNDLE_SUPPORT') + '/bin/latexmk.pl', '-CA', self.inputfile]
        commandParser = ParseLatexMk(None,self.verbose,self.fileName)
        result = runParsedProcess(texCommand, commandParser)
        stat = result.exitcode - result.signalcode
        self.increaseWarningCounts(result)
        return stat
    
    def run_clean(self):
        # TODO: this does not remove aux files created using include/input
        print('<h2>Clean output  files of %s</h2>' % (self.fileName))
        tempextensions = ['aux', 'bbl', 'blg', 'dvi', 'fdb_latexmk', 'glo', 'idx', 'ilg', 'ind', 'ist', 'log', 'out', 'pdfsync', 'pdf', 'ps', 'synctex.gz', 'toc']
        filecount = 0
        for extension in tempextensions:
            tempfile = self.outputfile + '.' + extension
            try:
                os.remove(tempfile)
                filecount += 1
            except (IOError, OSError):
                pass
        print('<p class="info">Removed %d files</p>' % filecount)
        return 0 # return OK status
    
    def findViewerPath(self,pdfFile):
        """Use the find_app command to ensure that the viewer is installed in the system
           For apps that support pdfsync search in pdf set up the command to go to the part of
           the page in the document the user was writing.
        """
        viewerPath = runOutputProcess([os.getenv('TM_SUPPORT_PATH')+'/bin/find_app', self.viewer+".app"])
        syncCommand = None
        if viewerPath:
            if self.viewer == 'Skim':
                syncCommand = [viewerPath + '/Contents/SharedSupport/displayline', str(os.getenv('TM_LINE_NUMBER')), pdfFile, os.getenv('TM_FILEPATH')]
            elif self.viewer == 'TeXniscope':
                syncCommand = [viewerPath + '/Contents/Resources/forward-search.sh', str(os.getenv('TM_LINE_NUMBER')), os.getenv('TM_FILEPATH'), pdfFile]
            elif self.viewer == 'PDFView':
                syncCommand = [viewerPath + '/Contents/MacOS/gotoline.sh', str(os.getenv('TM_LINE_NUMBER')), pdfFile]
        return viewerPath, syncCommand
    
    def refreshViewer(self,viewer,pdfFile):
        """Use Applescript to tell the viewer to reload"""
        print('<p class="info">Telling %s to Refresh %s...</p>'%(viewer,pdfFile))
        if viewer == 'Skim':
            #print "<pre>/usr/bin/osascript -e 'tell application \"Skim\" to revert document %s' </pre>" % shell_quote(pdfFile)  ## DEBUG
            os.system("/usr/bin/osascript -e " + """'tell application "Skim" to revert (documents whose path is %s)' """ % shell_quote(pdfFile))
        elif viewer == 'TeXniscope':
            #print "<pre>/usr/bin/osascript -e 'tell document %s of application \"TeXniscope\" to refresh' </pre>" % shell_quote(pdfFile)  ## DEBUG
            os.system("/usr/bin/osascript -e " + """'tell application "TeXniscope" to tell documents whose path is %s to refresh' """ % shell_quote(pdfFile))
        elif viewer == 'TeXShop':
            #print "<pre>/usr/bin/osascript -e 'tell document %s of application \"TeXShop\" to refreshpdf' </pre>" % shell_quote(pdfFile)  ## DEBUG
            os.system("/usr/bin/osascript -e " + """'tell application "TeXShop" to tell documents whose path is %s to refreshpdf' """ % shell_quote(pdfFile))
    
    def run_external_viewer(self):
        """Open the PDF in an external viewer.
           Ensure that the external viewer is installed and display the pdf.
        """
        stat = 0
        usePdfSync = ('pdfsync' in self.ltxPackages or self.syncTexSupport) # go to current line in PDF file
        pdfFile = self.outputNoSuffix+'.pdf' # relative path
        cmdPath,syncCommand = self.findViewerPath(pdfFile)
        if cmdPath:
            result = runProcess([os.getenv('TM_BUNDLE_PATH')+'/Support/bin/check_open', self.viewer, pdfFile])
            stat = result.exitcode
            if result.exitcode == 3:
                # technically: does not support the Apple Event to verify if a file is open.
                print('<p class="error">%s does not support open file verification. It is likely that it does neither support refreshing of open files, so you may want to use another PDF viewer.</p>' % self.viewer)
            if result.exitcode != 0:  # signal != 0 or return code != 0
                result = runProcess(['/usr/bin/open', '-a', self.viewer+'.app', pdfFile])
                stat = result.exitcode
                self.refreshViewer(self.viewer,pdfFile)            
            else:
                print("<pre>refreshViewer</pre>")
        else:
            print('<p class="error">', self.viewer, ' does not appear to be installed on your system.</p>')
        if usePdfSync:
            if syncCommand:
                # print "<pre>"+syncCommand+"</pre>"  ## DEBUG
                result = runProcess(syncCommand)
            else:
                print('pdfsync is not supported for this viewer')
        if stat != 0:
            print('<p class="error"><strong>error number %d opening viewer</strong></p>' % stat)
        return stat
    
    def run_texmate_viewer(self):
        """View the PDF in the TexMate log window.
           Setup the proper urls and/or redirects to show the pdf file in the html output window.
        """
        stat = 0
        # tmHref = '<p><a href="tm-file://'+quote(self.outputfile+'.pdf')+'">Click Here to View</a></p>'
        print('<script type="text/javascript">')
        print('window.location="tm-file://'+quote(self.outputfile+'.pdf')+'"')
        print('</script>')
        self.keepLogWindow = True
        # Check status of running the viewer
    
    def constructEngineOptions(self):
        """Construct a string of command line options to pass to the typesetting engine
        Options can come from:
        +  %!TEX TS-options directive in the file
        + Preferences
        In any case nonstopmode is set as is file-line-error-style.
        """
        opts = "-interaction=nonstopmode -file-line-error-style"
        if self.syncTexSupport:
            opts += " -synctex=1 "
        if 'TS-options' in self.tsDirs:
            opts += " " + self.tsDirs['TS-options']
        else:
            opts += " " + self.tmPrefs['latexEngineOptions']
        return opts
    
    def writeLatexmkRc(self):
        """Create a latexmkrc file that uses the proper engine and arguments"""
        rcFile = open("/tmp/latexmkrc",'w')
        engineoptions = self.constructEngineOptions()
        rcFile.write("""$latex = 'latex %s  ';\n""" % (engineoptions))
        rcFile.write("""$pdflatex = '%s %s ';\n""" % (self.engine, engineoptions))
        ## DEBUG:
        #print "<pre>/tmp/latexmkrc="
        print("""$latex = 'latex -interaction=nonstopmode -file-line-error-style %s  ';""" % engineoptions)
        print("""$pdflatex = '%s -interaction=nonstopmode -file-line-error-style %s ';""" % (self.engine, engineoptions))
        print("</pre>")
        # rcFile.write("""$bibtex = 'bibtex "%%B"';\n""")
        # rcFile.write("""$dvips = 'dvips %O "%S" -o "%D"';\n""")
        # rcFile.write("""$dvipdf = 'dvipdf %O "%S" "%D"';\n""")
        # rcFile.write("""$clean_full_ext = "maf mtc mtc1 mtc2 mtc3";\n""")
        rcFile.close()
    
    def printButtons(self):
        """Output buttons at the bottom of the window."""
        js = os.getenv('TM_BUNDLE_SUPPORT') + '/bin/texlib.js'
        print('<script src="file://%s" type="text/javascript" charset="utf-8"></script>' % quote(js))
        
        print('<div id="texActions">')
        print('<input type="button" value="Re-Run %s" onclick="runLatex(); return false" />' % self.engine)
        print('<input type="button" value="Run BibTeX" onclick="runBibtex(); return false" />')
        print('<input type="button" value="Run Makeindex" onclick="runMakeIndex(); return false" />')
        print('<input type="button" value="Clean up" onclick="runClean(); return false" />')        
        if self.viewer == 'TextMate':
            print("""<input type="button" value="view in TextMate" onclick="window.location='""" + 'tm-file://' + quote(self.outputfile+'.pdf') +"""'"/>""")
        else:
            print('<input type="button" value="View in %s" onclick="runView(); return false" />' % self.viewer)
        print('<input type="button" value="Preferences…" onclick="runConfig(); return false" />')
        print('<p>')
        print('<input type="checkbox" id="hv_warn" name="fmtWarnings" onclick="makeFmtWarnVisible(); return false" />')
        print('<label for="hv_warn">Show hbox,vbox Warnings </label></p>')            
        print('</div>')


###############################################################
#                                                             #
#                 Start of main program...                    #
#                                                             #
###############################################################


if __name__ == '__main__':
    # Parse command line parameters...
    firstRun = False
    if len(sys.argv) > 2:
        firstRun = True         ## A little hack to make the buttons work nicer.
    if len(sys.argv) > 1:
        action = sys.argv[1]
    else:
        sys.stderr.write("Usage: "+sys.argv[0]+" tex-command firstRun\n")
        sys.exit(64)  # EX_USAGE
    
    # Initializes program: reads preferences, etc.
    program = TexMate(firstRun)
    # Take action ("latex", "bibtex", "makeindex", "view", "clean" or "make").
    # An action may result in execution of multiple programs. E.g. "pdflatex" and "view"
    eCode = program.do_action(action)
    sys.exit(eCode)

