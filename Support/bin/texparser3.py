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
from struct import *
from xml.sax.saxutils import escape
try:
    from urllib.parse import quote  # python 3
except ImportError:
    from urllib import quote  # python 2
import io  # only works on 2.6 or up


def make_link(file, line):
    """A custom version of urlparse.urlunparse()"""
    file = os.path.realpath(os.path.join(os.getcwd(), file)) # make absolute, (works fine even if it was already absolute)
    return 'txmt://open?url=file:%2F%2F' + quote(file, '') + '&amp;line=' + str(line)

class TexParser(object):
    """Master Class for Parsing Tex Typsetting Streams"""
    def __init__(self, input_stream, verbose, fileName=None):
        super(TexParser, self).__init__()
        self.fileName = fileName
        self.setInput(input_stream)
        self.patterns = []
        self.done = False
        self.verbose = verbose
        self.numErrs = 0
        self.numWarns = 0
        self.isFatal = False
        self.numRuns = 0
    
    def setInput(self, input_stream):
        self.input_stream = input_stream
    
    def parseLine(self, line):
        """Process a single line"""
        
        # process matching patterns until we find one
        foundMatch = False
        for pat,fun in self.patterns:
            myMatch = pat.match(line)
            if myMatch:
                fun(myMatch,line)
                sys.stdout.flush()
                foundMatch = True
                break
        if self.verbose and not foundMatch:
            print(escape(line))
    
    def parseStream(self):
        """Process the input_stream one line at a time, matching against
           each pattern in the patterns dictionary.  If a pattern matches
           call the corresponding method in the dictionary.  The dictionary
           is organized with patterns as the keys and methods as the values."""
        line = self.input_stream.readline()
        
        while line and not self.done:
            line = line.rstrip("\n")
            
            self.parseLine(line)
            
            line = self.input_stream.readline()
        self.wrapup()
        return self.isFatal, self.numErrs, self.numWarns
    
    def wrapup(self):
        if self.done == False:
            self.badRun()
        if self.numRuns == 0:
            self.numRuns = 1
    
    def info(self,m,line):
        print('<p class="info">')
        print(escape(line))
        print('</p>')
    
    def error(self,m,line):
        print('<p class="error">')
        print(escape(line))
        print('</p>')
        self.numErrs += 1
    
    def warning(self,m,line):
        print('<p class="warning">')
        print(escape(line))
        print('</p>')
        self.numWarns += 1
    
    def warn2(self,m,line):
        print('<p class="fmtWarning">')
        print(escape(line))
        print('</p>')
    
    def fatal(self,m,line):
        print('<p class="error">')
        print(escape(line))
        print('</p>')
        self.isFatal = True
    
    def badRun(self):
        """docstring for finishRun"""
        pass
    

class MkIndexParser(TexParser):
    """Parse and format Error Messages from makeindex"""
    def __init__(self, btex, verbose, fileName=None):
        super(MkIndexParser, self).__init__(btex,verbose,fileName)
        self.patterns += [ 
            (re.compile("Input index file (.*) not found") , self.noInputError)
        ]
    
    def noInputError(self,m,line):
        print('<p class="error">')
        print(escape(line))
        print('</p>')
        print('<p class="info">')
        print("Make sure your latex file includes <code>\\usepackage{makeidx} \makeindex</code> and run latex before running makeindex.")
        print('</p>')
        self.numErrs += 1
    

class BibTexParser(TexParser):
    """Parse and format Error Messages from bibtex"""
    def __init__(self, btex, verbose, fileName=None):
        super(BibTexParser, self).__init__(btex,verbose,fileName)
        self.numNobiblioErrs = 0
        self.patterns += [ 
            (re.compile("Warning--(.*)") , self.warning),
            (re.compile("--line (\d+) of file (.*)") , self.handleFileLineReference),
            (re.compile(r'I found no \\\w+ command') , self.warning),
            (re.compile(r"I couldn't open style file"), self.error),
            (re.compile(r"I couldn't open \w+ file"), self.error),
            (re.compile('This is BibTeX') , self.info),
            (re.compile('The style') , self.info),            
            (re.compile('Database') , self.info),                        
            (re.compile('---') , self.finishRun)
        ]
    
    def handleFileLineReference(self,m,line):
        # TODO: fix
        """Display warning. match m should contain file, line, warning message. Ideally, this line should be merged with the previous line, but this would require that getRewrappedLine also merges these lines."""
        print('<p><a href="' + make_link(m.group(2),m.group(1)) + '">' + escape(line) + "</a></p>")
        self.numWarns += 1
    
    def finishRun(self,m,line):
        self.done = True
    

class LaTexParser(TexParser):
    """Parse Output From Latex"""
    def __init__(self, input_stream, verbose, fileName=None):
        super(LaTexParser, self).__init__(input_stream,verbose,fileName)
        self.outputFile = ""
        if fileName:
            self.fileStack = [fileName]
        else:
            self.fileStack = []
        self.currentFile = ""
        self.exts = set(['.tex']) # files with these extensions are displayed. Includes dot
        if self.fileName and len(os.path.splitext(self.fileName)) > 1:
            self.exts.add(os.path.splitext(self.fileName)[1]) # extension with dot
        # NOTE: to support file names with accented chars, the line needs to be a Unicode string 
        # instead of a binary string (e.g. u"line" instead of "line".) In addition, add the re.UNICODE 
        # flag to each regexp. That would be sufficient for regexps with \w in the name. That does 
        # not help for file names with spaces in the name. Also, I doubt that latex supports files 
        # names with accented chars, especially because HFS+ uses NFD (decomposed) Unicode chars, 
        # while most UNIX tools expect NFC (precomposed) chars.
        self.patterns += [
            (re.compile('This is') , self.info),
            (re.compile('Document Class') , self.info),
            (re.compile('.*\<use (.*?)\>') , self.detectInclude),
            (re.compile('Output written on (.*) (\(.*\))') , self.outputInfo),
            (re.compile('LaTeX Warning:.*?input line (\d+)(\.|$)') , self.handleWarning),
            (re.compile('Package \w+ Warning:.*?input line (\d+)(\.|$)') , self.handleWarning),
            (re.compile('LaTeX Warning:.*') , self.warning),
            (re.compile('Package \w+ Warning:.*') , self.warning),
            (re.compile('([^:]*):(\d+):\s+(pdfTeX warning.*)') , self.handleFileLineWarning),
            (re.compile('.*pdfTeX warning.*') , self.warning),
            (re.compile('LaTeX Font Warning:.*') , self.warning),
            (re.compile('Overfull.*wide') , self.warn2),
            (re.compile('Underfull.*badness') , self.warn2),
            (re.compile('([^:]*):(\d+): LaTeX Error:(.*)') , self.handleError),
            (re.compile('([^:]*):(\d+): (Emergency stop)') , self.handleError),
            (re.compile('.*?([^:]+\.\w+):(\d+):\s+(.*)') , self.handleError),
            (re.compile('Transcript written on (.*)\.$') , self.finishRun),
            (re.compile('Error: pdflatex') , self.pdfLatexError),
            (re.compile('\!.*') , self.handleOldStyleErrors),
            (re.compile('\s+==>') , self.fatal)
        ]
        self.blankLine = re.compile(r'^\s*$')        
    
    def setInput(self, input_stream):
        # Decorate input_stream with formatters that reformats the log lines to single log statements
        self.input_stream = NoMultilinePackageWarning(NoMultilineWarning(LinebreakWarning(NoLinebreak80(input_stream))))
        # self.input_stream = input_stream
    
    def getLastFile(self):
        """Returns the short name of the last file present in self.fileStack.
        self.fileStack contains a lot of bogus and irrelevant entries.
        e.g. 'verson 3.14 (Web2C)' or .clo, .sty, .ldf files instead of .tex files"""
        # Typical matches: '', '.', '.\d+', '.\d+pt', '.aux', '.bbl', '.cfg', '.clo', '.cls', '.def', '.fd', '.ldf', '.out',  '.sty', '.tex', '.toc', 
        for filename in reversed(self.fileStack):
            if os.path.splitext(filename)[1] in self.exts:
                return filename
        return ""
    
    def parseLine(self, line):
        """Process a single line"""
        # Find parsed file names
        filematch = re.compile(r'([\(\)])([\w/\.\-]*)')  # matches '(filename.tex' or ')'
        for (openclose, filename) in filematch.findall(line):
            if openclose == '(':
                self.fileStack.append(filename)
                newfile = self.getLastFile() # see if this changes the "active" file
                if newfile != self.currentFile:
                    print("<h4>Processing: " + escape(newfile) + "</h4>")
                    self.currentFile = newfile
            elif len(self.fileStack) > 0:
                self.fileStack.pop()
                # self.currentFile = self.getLastFile()
                newfile = self.getLastFile() # see if this changes the "active" file
                if newfile != self.currentFile:
                    print("<h4>Resume processing: " + escape(newfile) + "</h4>")
                    self.currentFile = newfile
        
        # process matching patterns until we find one
        TexParser.parseLine(self, line)
    
    def detectInclude(self,m,line):
        print("<ul><li>Including: " + escape(m.group(1)))
        print("</li></ul>")
    
    def handleWarning(self,m,line):
        """Display warning. match m should contain line, warning message"""
        print('<p class="warning"><a href="' + make_link(self.currentFile, m.group(1)) + '">'+escape(line)+"</a></p>")
        self.numWarns += 1
    
    def handleFileLineWarning(self,m,line):
        """Display warning. match m should contain file, line, warning message"""
        print('<p class="warning"><a href="' + make_link(m.group(1),m.group(2)) + '">' + escape(m.group(3)) + "</a></p>")
        self.numWarns += 1
    
    def handleError(self,m,line):
        """Display error. match m should contain file, line, error message"""
        print('<p class="error">')
        print('Latex Error: <a  href="' + make_link(m.group(1),m.group(2)) +  '">' + escape(m.group(1)+":"+m.group(2)) + '</a> '+escape(m.group(3))+'</p>')
        self.numErrs += 1
    
    def finishRun(self,m,line):
        logFile = m.group(1).strip('"')
        print('<p>Complete transcript is in ')
        print('<a href="' + make_link(logFile,'1') +  '">' + escape(logFile) + '</a>')
        print('</p>')
        self.done = True
    
    def outputInfo(self,m,line):
        self.outputFile = m.group(1).strip('"')
        print('<p class="info">Output written on <a href="%s">%s</a> (%s)</p>' % (self.outputFile, escape(m.group(1)), escape(m.group(2))))
    
    def handleOldStyleErrors(self,m,line):
        if re.search('[Ee]rror', line):
            print('<p class="error">')
            print(escape(line))
            print('</p>')
            self.numErrs += 1
        else:
            print('<p class="warning">')
            print(escape(line))
            print('</p>')
            self.numWarns += 1
    
    def pdfLatexError(self,m,line):
        """docstring for pdfLatexError"""
        self.numErrs += 1
        print('<p class="error">')
        print(escape(line))
        line = self.input_stream.readline()
        if line and re.match('^ ==> Fatal error occurred', line):  
            print(escape(line.rstrip("\n")))
            print('</p>')
            self.isFatal = True
        else:
            print('</p>')
        sys.stdout.flush()
    
    def badRun(self):
        """docstring for finishRun"""
        # logfile location is wrong for different output directory, but fixing this is not worth the effort.
        logfile = os.path.splitext(self.fileName)[0]+'.log'
        print('<p class="error">Output of program terminated prematurely. Logfile is in <a href="%s">%s</a></p>' % (make_link(logfile,1), escape(logfile)))
    

class ParseLatexMk(TexParser):
    """docstring for ParseLatexMk"""
    def __init__(self, input_stream, verbose,fileName=None):
        super(ParseLatexMk, self).__init__(input_stream,verbose,fileName)
        self.patterns += [
            (re.compile('This is (pdfTeXk|latex2e|latex|XeTeXk)') , self.startLatex),
            (re.compile('This is BibTeX') , self.startBibtex),
            (re.compile('^Latexmk: All targets \(.*?\) are up-to-date') , self.finishRun),
            (re.compile('This is makeindex') , self.startBibtex),
            (re.compile('^Latexmk') , self.ltxmk),
            (re.compile('Run number') , self.newRun)
        ]
    
    def startBibtex(self,m,line):
        print('<div class="bibtex">')
        print('<h3>' + escape(line[:-1]) + '</h3>')
        bp = BibTexParser(self.input_stream,self.verbose)
        f,e,w = bp.parseStream()
        self.numErrs += e
        self.numWarns += w
        print('</div>')
    
    def startLatex(self,m,line):
        print('<div class="latex">')
        print('<hr>')
        print('<h3>' + escape(line[:-1]) + '</h3>')
        bp = LaTexParser(self.input_stream,self.verbose,self.fileName)
        f,e,w = bp.parseStream()
        self.numErrs += e
        self.numWarns += w
        print('</div>')
    
    def newRun(self,m,line):
        if self.numRuns > 0:
            print('<hr />')
            print('<p>', self.numErrs, 'Errors', self.numWarns, 'Warnings', 'in this run.', '</p>')
        self.numWarns = 0
        self.numErrs = 0
        self.numRuns += 1
    
    def finishRun(self,m,line):
        self.ltxmk(m,line)
        self.done = True
    
    def ltxmk(self,m,line):
        print('<p class="ltxmk">%s</p>'%escape(line))
    

class StreamWrapper(io.TextIOWrapper):  # open is an alias of class io.TextIOWrapper
    """Sometimes TeX breaks up lines with hard linebreaks.  This is annoying.
    Even more annoying is that it sometime does not break line, for two distinct 
    warnings. This class decorates the stdin file object, and modifies the 
    readline function to return more appropriate units (log statements rather than log lines).
    """
    def __init__(self,input_stream):
        self.input_stream = input_stream
    def readline(self):
        return self.input_stream.readline()

class NoLinebreak80(StreamWrapper):
    """TeX inserts hard line breaks if the length of a line exceeds 80 chars.
    This wrappers undos that behaviour by removing line breaks with lines of exactly 80 chars length"""
    def readline(self):
        statement = ""
        while True:
            line = self.input_stream.readline()
            if not line: # EOF
                return statement
            if len(line) == 80: # continue the loop for lines of 80 chars incl. line break
                statement += line.rstrip("\n")
            else:
                statement += line
                break
        return statement

class LinebreakWarning(StreamWrapper):
    """TeX often doesn't break a line. This wrapper tries to at least insert a line break 
    before a warning or error. It matches line like 
    sometext1234 pdfTeX warning (ext4): destination with the same identifier"""
    def __init__(self,input_stream):
        StreamWrapper.__init__(self,input_stream)
        self.buffer = ""
        self.pattern = re.compile('(.*[^a-zA-Z])([a-zA-Z]*[Tt]e[Xx] (?:warning|error).*)')
    def readline(self):
        if self.buffer != "":
            statement = self.buffer
            self.buffer = ""
            return statement
        line = self.input_stream.readline()
        if not line: # EOF
            return line
        match = self.pattern.match(line)
        if match:
            self.buffer = match.group(2)
            return match.group(1)
        return line

class NoMultilineWarning(StreamWrapper):
    """LaTeX sometimes prints a warning over multiple lines.
    This wrapper makes those warning into one line. Continuation lines
    are expected to start with multiple spaces. It matches warnings like:
    LaTeX Warning: You have requested package `styles/cases',
                   but the package provides `cases'."""
    def __init__(self,input_stream):
        StreamWrapper.__init__(self,input_stream)
        self.buffer = ""
    def getline(self):
        if self.buffer:
            line = self.buffer
            self.buffer = ""
            return line
        else:
            return self.input_stream.readline()
    def readline(self):
        statement = self.getline()
        if not statement: # EOF
            return statement
        continuation = statement.startswith("LaTeX Warning")
        while continuation:
            line = self.getline()
            if line.startswith("  "):
                statement = statement.rstrip("\n")+" "+line.lstrip()
            else:
                self.buffer = line
                continuation = False
        return statement


class NoMultilinePackageWarning(StreamWrapper):
    """Some packages print a warning over multiple lines.
    This wrapper makes those warning into one line. Continuation lines
    are expected to start with multiple spaces. It matches warnings like:
    Package amsmath Warning: Cannot use `split' here;
    (amsmath)                trying to recover with `aligned'
    """
    def __init__(self,input_stream):
        StreamWrapper.__init__(self,input_stream)
        self.buffer = ""
        self.firstlinere = re.compile('Package (\w+) Warning:.*')
    def getline(self):
        if self.buffer != "":
            line = self.buffer
            self.buffer = ""
            return line
        else:
            return self.input_stream.readline()
    def readline(self):
        statement = self.getline()
        if not statement: # EOF
            return statement
        match = self.firstlinere.match(statement)
        if match:
            contstart = '('+match.group(1)+')'
            continuation = True
        else:
            continuation = False
        while continuation:
            line = self.getline()
            if line.startswith(contstart):
                statement = statement.rstrip("\n") + " " + line[len(contstart):].lstrip()
            else:
                self.buffer = line
                continuation = False
        return statement


if __name__ == '__main__':
    # test
    stream = open('../tex/test.log')
    lp = LaTexParser(stream,False,"test.tex")
    f,e,w = lp.parseStream()

