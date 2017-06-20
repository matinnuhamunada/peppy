""" Helpers without an obvious logical home. """

from argparse import ArgumentParser
from collections import Counter, defaultdict, Iterable
import logging
import os
import subprocess as sp
import yaml
from ._version import __version__


_LOGGER = logging.getLogger(__name__)



class VersionInHelpParser(ArgumentParser):
    def format_help(self):
        """ Add version information to help text. """
        return "version: {}\n".format(__version__) + \
               super(VersionInHelpParser, self).format_help()



def alpha_cased(text, lower=False):
    """
    Filter text to just letters and homogenize case.

    :param str text: what to filter and homogenize.
    :param bool lower: whether to convert to lowercase; default uppercase.
    :return str: input filtered to just letters, with homogenized case.
    """
    text = "".join(filter(lambda c: c.isalpha(), text))
    return text.lower() if lower else text.upper()



def check_bam(bam, o):
    """
    Check reads in BAM file for read type and lengths.

    :param str bam: BAM file path.
    :param int o: Number of reads to look at for estimation.
    """
    try:
        p = sp.Popen(['samtools', 'view', bam], stdout=sp.PIPE)
        # Count paired alignments
        paired = 0
        read_length = Counter()
        while o > 0:  # Count down number of lines
            line = p.stdout.readline().decode().split("\t")
            flag = int(line[1])
            read_length[len(line[9])] += 1
            if 1 & flag:  # check decimal flag contains 1 (paired)
                paired += 1
            o -= 1
        p.kill()
    except OSError:
        reason = "Note (samtools not in path): For NGS inputs, " \
                 "looper needs samtools to auto-populate " \
                 "'read_length' and 'read_type' attributes; " \
                 "these attributes were not populated."
        raise OSError(reason)

    _LOGGER.debug("Read lengths: {}".format(read_length))
    _LOGGER.debug("paired: {}".format(paired))
    return read_length, paired



def check_fastq(fastq, o):
    raise NotImplementedError("Detection of read type/length for "
                              "fastq input is not yet implemented.")



def fetch_package_classes(pkg, predicate=None):
    """
    Enable single-depth fetch of package's classes if not exported.

    :param module pkg: the package of interest.
    :param function(type) -> bool predicate: condition each class must
        satisfy in order to be returned.
    :return Iterable(type): classes one layer deep within the package, that
        satisfy the condition if given.
    """
    import inspect
    import itertools

    modules = [pkg] if inspect.ismodule(pkg) else \
            [obj for obj in inspect.getmembers(
                    pkg, lambda member: inspect.ismodule(member))]
    return list(itertools.chain(
            *[inspect.getmembers(mod, predicate) for mod in modules]))



def get_file_size(filename):
    """
    Get size of all files in gigabytes (Gb).

    :param str | collections.Iterable[str] filename: A space-separated
        string or list of space-separated strings of absolute file paths.
    :return float: size of file(s), in gigabytes.
    """
    if filename is None:
        return float(0)
    if type(filename) is list:
        return float(sum([get_file_size(x) for x in filename]))
    try:
        total_bytes = sum([float(os.stat(f).st_size)
                           for f in filename.split(" ") if f is not ''])
    except OSError:
        # File not found
        return 0.0
    else:
        return float(total_bytes) / (1024 ** 3)



def import_from_source(name, module_filepath):
    """
    Import a module from a particular filesystem location.

    :param str name: name for the module when loaded
    :param str module_filepath: path to the file that constitutes the module
        to import
    :return module: module imported from the given location, named as indicated
    :raises ValueError: if path provided does not point to an extant file
    :raises ImportError: if path provided is indeed an existing file, but the
    """
    import sys

    if not os.path.exists(module_filepath):
        raise ValueError("Path to alleged module file doesn't point to an "
                         "extant file: '{}'".format(module_filepath))

    if sys.version_info >= (3, 5):
        from importlib import util as _il_util
        modspec = _il_util.spec_from_file_module_filepath(
            name, module_filepath)
        mod = _il_util.module_from_spec(modspec)
        modspec.loader.exec_module(mod)
    elif sys.version_info < (3, 3):
        import imp
        mod = imp.load_source(name, module_filepath)
    else:
        # 3.3 or 3.4
        from importlib import machinery as _il_mach
        loader = _il_mach.SourceFileLoader(name, module_filepath)
        mod = loader.load_module()

    return mod



def parse_ftype(input_file):
    """
    Checks determine filetype from extension.

    :param str input_file: String to check.
    :return str: filetype (extension without dot prefix)
    :raises TypeError: if file does not appear of a supported type
    """
    if input_file.endswith(".bam"):
        return "bam"
    elif input_file.endswith(".fastq") or \
            input_file.endswith(".fq") or \
            input_file.endswith(".fq.gz") or \
            input_file.endswith(".fastq.gz"):
        return "fastq"
    else:
        raise TypeError("Type of input file ends in neither '.bam' "
                        "nor '.fastq' [file: '" + input_file + "']")



def parse_text_data(lines_or_path, delimiter=os.linesep):
    """
    Interpret input argument as lines of data. This is intended to support
    multiple input argument types to core model constructors.

    :param str | collections.Iterable lines_or_path:
    :param str delimiter: line separator used when parsing a raw string that's
        not a file
    :return collections.Iterable: lines of text data
    :raises ValueError: if primary data argument is neither a string nor
        another iterable
    """

    if os.path.isfile(lines_or_path):
        with open(lines_or_path, 'r') as f:
            return f.readlines()
    else:
        _LOGGER.debug("Not a file: '{}'".format(lines_or_path))

    if isinstance(lines_or_path, str):
        return lines_or_path.split(delimiter)
    elif isinstance(lines_or_path, Iterable):
        return lines_or_path
    else:
        raise ValueError("Unable to parse as data lines {} ({})".
                         format(lines_or_path, type(lines_or_path)))



def partition(items, test):
    """
    Partition items into a pair of disjoint multisets,
    based on the evaluation of each item as input to boolean test function.
    There are a couple of evaluation options here. One builds a mapping
    (assuming each item is hashable) from item to boolean test result, then
    uses that mapping to partition the elements on a second pass.
    The other simply is single-pass, evaluating the function on each item.
    A time-costly function suggests the two-pass, mapping-based approach while
    a large input suggests a single-pass approach to conserve memory. We'll
    assume that the argument is not terribly large and that the function is
    cheap to compute and use a simpler single-pass approach.

    :param Sized[object] items: items to partition
    :param function(object) -> bool test: test to apply to each item to
        perform the partitioning procedure
    :return: list[object], list[object]: partitioned items sequences
    """
    passes, fails = [], []
    _LOGGER.log(5, "Testing {} items: {}".format(len(items), items))
    for item in items:
        _LOGGER.log(5, "Testing item {}".format(item))
        group = passes if test(item) else fails
        group.append(item)
    return passes, fails



class CommandChecker(object):
    """
    Validate PATH availability of executables referenced by a config file.

    :param path_conf_file: path to configuration file with
        sections detailing executable tools to validate
    :type path_conf_file: str
    :param sections_to_check: names of
        sections of the given configuration file that are relevant;
        optional, will default to all sections if not given, but some
        may be excluded via another optional parameter
    :type sections_to_check: Iterable[str]
    :param sections_to_skip: analogous to
        the check names parameter, but for specific sections to skip.
    :type sections_to_skip: Iterable[str]

    """


    def __init__(self, path_conf_file,
                 sections_to_check=None, sections_to_skip=None):

        super(CommandChecker, self).__init__()

        self._logger = logging.getLogger(
            "{}.{}".format(__name__, self.__class__.__name__))

        # TODO: could provide parse strategy as parameter to supplement YAML.
        # TODO: could also derive parsing behavior from extension.
        self.path = path_conf_file
        with open(self.path, 'r') as conf_file:
            conf_data = yaml.safe_load(conf_file)

        # Determine which sections to validate.
        sections = {sections_to_check} if isinstance(sections_to_check, str) \
            else set(sections_to_check or conf_data.keys())
        excl = {sections_to_skip} if isinstance(sections_to_skip, str) \
            else set(sections_to_skip or [])
        sections -= excl

        self._logger.info("Validating %d sections: %s",
                          len(sections),
                          ", ".join(["'{}'".format(s) for s in sections]))

        # Store per-command mapping of status, nested under section.
        self.section_to_status_by_command = defaultdict(dict)
        # Store only information about the failures.
        self.failures_by_section = defaultdict(list)  # Access by section.
        self.failures = set()  # Access by command.

        for s in sections:
            # Fetch section data or skip.
            try:
                section_data = conf_data[s]
            except KeyError:
                _LOGGER.info("No section '%s' in file '%s', skipping",
                             s, self.path)
                continue
            # Test each of the section's commands.
            try:
                # Is section's data a mapping?
                commands_iter = section_data.items()
                self._logger.debug("Processing section '%s' data "
                                   "as mapping", s)
                for name, command in commands_iter:
                    failed = self._store_status(section=s, command=command,
                                                name=name)
                    self._logger.debug("Command '%s': %s", command,
                                       "FAILURE" if failed else "SUCCESS")
            except AttributeError:
                self._logger.debug("Processing section '%s' data as list", s)
                commands_iter = conf_data[s]
                for cmd_item in commands_iter:
                    # Item is K-V pair?
                    try:
                        name, command = cmd_item
                    except ValueError:
                        # Treat item as command itself.
                        name, command = "", cmd_item
                    success = self._store_status(section=s, command=command,
                                                 name=name)
                    self._logger.debug("Command '%s': %s", command,
                                       "SUCCESS" if success else "FAILURE")


    def _store_status(self, section, command, name):
        """
        Based on new command execution attempt, update instance's
        data structures with information about the success/fail status.
        Return the result of the execution test.
        """
        succeeded = is_command_callable(command, name)
        # Store status regardless of its value in the instance's largest DS.
        self.section_to_status_by_command[section][command] = succeeded
        if not succeeded:
            # Only update the failure-specific structures conditionally.
            self.failures_by_section[section].append(command)
            self.failures.add(command)
        return succeeded


    @property
    def failed(self):
        """
        Determine whether *every* command succeeded for *every* config file
        section that was validated during instance construction.

        :return bool: conjunction of execution success test result values,
            obtained by testing each executable in every validated section
        """
        # This will raise exception even if validation was attempted,
        # but no sections were used. Effectively, delegate responsibility
        # to the caller to initiate validation only if doing so is relevant.
        if not self.section_to_status_by_command:
            raise ValueError("No commands validated")
        return 0 == len(self.failures)



def is_command_callable(command, name=""):
    """
    Check if command can be called.

    :param str command: actual command to call
    :param str name: nickname/alias by which to reference the command, optional
    :return bool: whether given command's call succeeded
    """

    # Use `command` to see if command is callable, store exit code
    code = os.system(
        "command -v {0} >/dev/null 2>&1 || {{ exit 1; }}".format(command))

    if code != 0:
        alias_value = " ('{}') ".format(name) if name else " "
        _LOGGER.debug("Command{0}is not callable: {1}".
                      format(alias_value, command))
    return not bool(code)
