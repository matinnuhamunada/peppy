""" Helpers without an obvious logical home. """

from collections import defaultdict, Iterable
import contextlib
import logging
import os
import random
import string
import subprocess as sp
import sys
if sys.version_info < (3, 0):
    from urlparse import urlparse
else:
    from urllib.parse import urlparse
if sys.version_info < (3, 3):
    from collections import Sized
else:
    from collections.abc import Sized
import warnings
import yaml
from .const import SAMPLE_INDEPENDENT_PROJECT_SECTIONS


_LOGGER = logging.getLogger(__name__)


__all__ = [
    "CommandChecker", "add_project_sample_constants", "check_bam", "check_fastq",
    "check_sample_sheet_row_count", "get_file_size", "fetch_samples",
    "grab_project_data", "has_null_value", "is_command_callable"
]


def add_project_sample_constants(sample, project):
    """
    Update a Sample with constants declared by a Project.

    :param Sample sample: sample instance for which to update constants
        based on Project
    :param Project project: Project with which to update Sample; it
        may or may not declare constants. If not, no update occurs.
    :return Sample: Updates Sample instance, according to any and all
        constants declared by the Project.
    """
    sample.update(project.constants)
    return sample


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
        read_lengths = defaultdict(int)
        while o > 0:  # Count down number of lines
            line = p.stdout.readline().decode().split("\t")
            flag = int(line[1])
            read_lengths[len(line[9])] += 1
            if 1 & flag:  # check decimal flag contains 1 (paired)
                paired += 1
            o -= 1
        p.kill()
    except OSError:
        reason = "Note (samtools not in path): For NGS inputs, " \
                 "pep needs samtools to auto-populate " \
                 "'read_length' and 'read_type' attributes; " \
                 "these attributes were not populated."
        raise OSError(reason)

    _LOGGER.debug("Read lengths: {}".format(read_lengths))
    _LOGGER.debug("paired: {}".format(paired))
    return read_lengths, paired


def check_fastq(fastq, o):
    raise NotImplementedError("Detection of read type/length for "
                              "fastq input is not yet implemented.")


def coll_like(c):
    """
    Determine whether an object is collection-like.

    :param object c: Object to test as collection
    :return bool: Whether the argument is a (non-string) collection
    """
    return isinstance(c, Iterable) and not isinstance(c, str)


def copy(obj):
    def copy(self):
        """
        Copy self to a new object.
        """
        from copy import deepcopy

        return deepcopy(self)
    obj.copy = copy
    return obj


def expandpath(path):
    """
    Expand a filesystem path that may or may not contain user/env vars.

    :param str path: path to expand
    :return str: expanded version of input path
    """
    return os.path.expandvars(os.path.expanduser(path)).replace("//", "/")


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


def fetch_samples(proj, selector_attribute=None, selector_include=None, selector_exclude=None):
    """
    Collect samples of particular protocol(s).

    Protocols can't be both positively selected for and negatively
    selected against. That is, it makes no sense and is not allowed to
    specify both selector_include and selector_exclude protocols. On the other hand, if
    neither is provided, all of the Project's Samples are returned.
    If selector_include is specified, Samples without a protocol will be excluded,
    but if selector_exclude is specified, protocol-less Samples will be included.

    :param Project proj: the Project with Samples to fetch
    :param Project str: the sample selector_attribute to select for
    :param Iterable[str] | str selector_include: protocol(s) of interest;
        if specified, a Sample must
    :param Iterable[str] | str selector_exclude: protocol(s) to include
    :return list[Sample]: Collection of this Project's samples with
        protocol that either matches one of those in selector_include, or either
        lacks a protocol or does not match one of those in selector_exclude
    :raise TypeError: if both selector_include and selector_exclude protocols are
        specified; TypeError since it's basically providing two arguments
        when only one is accepted, so remain consistent with vanilla Python2
    """
    if selector_attribute is None or (not selector_include and not selector_exclude):
        # Simple; keep all samples.  In this case, this function simply
        # offers a list rather than an iterator.
        return list(proj.samples)

    # At least one of the samples has to have the specified attribute
    if proj.samples and not any([hasattr(i, selector_attribute) for i in proj.samples]):
        raise AttributeError("The Project samples do not have the attribute '{attr}'"
                             .format(attr=selector_attribute))

    # Intersection between selector_include and selector_exclude is nonsense user error.
    if selector_include and selector_exclude:
        raise TypeError("Specify only selector_include or selector_exclude parameter, "
                         "not both.")

    # Ensure that we're working with sets.
    def make_set(items):
        if isinstance(items, str):
            items = [items]
        return items

    # Use the attr check here rather than exception block in case the
    # hypothetical AttributeError would occur; we want such
    # an exception to arise, not to catch it as if the Sample lacks "protocol"
    if not selector_include:
        # Loose; keep all samples not in the selector_exclude.
        def keep(s):
            return not hasattr(s, selector_attribute) or \
                   getattr(s, selector_attribute) not in make_set(selector_exclude)
    else:
        # Strict; keep only samples in the selector_include.
        def keep(s):
            return hasattr(s, selector_attribute) and \
                   getattr(s, selector_attribute) in make_set(selector_include)

    return list(filter(keep, proj.samples))


def grab_project_data(prj):
    """
    From the given Project, grab Sample-independent data.

    There are some aspects of a Project of which it's beneficial for a Sample
    to be aware, particularly for post-hoc analysis. Since Sample objects
    within a Project are mutually independent, though, each doesn't need to
    know about any of the others. A Project manages its, Sample instances,
    so for each Sample knowledge of Project data is limited. This method
    facilitates adoption of that conceptual model.

    :param Project prj: Project from which to grab data
    :return Mapping: Sample-independent data sections from given Project
    """
    if not prj:
        return {}
    data = {}
    for section in SAMPLE_INDEPENDENT_PROJECT_SECTIONS:
        try:
            data[section] = getattr(prj, section)
        except AttributeError:
            _LOGGER.debug("Project lacks section '%s', skipping", section)
    return data


def has_null_value(k, m):
    """
    Determine whether a mapping has a null value for a given key.

    :param Hashable k: Key to test for null value
    :param Mapping m: Mapping to test for null value for given key
    :return bool: Whether given mapping contains given key with null value
    """
    return k in m and is_null_like(m[k])


def import_from_source(module_filepath):
    """
    Import a module from a particular filesystem location.

    :param str module_filepath: path to the file that constitutes the module
        to import
    :return module: module imported from the given location, named as indicated
    :raises ValueError: if path provided does not point to an extant file
    """
    import sys

    if not os.path.exists(module_filepath):
        raise ValueError("Path to alleged module file doesn't point to an "
                         "extant file: '{}'".format(module_filepath))

    # Randomly generate module name.
    fname_chars = string.ascii_letters + string.digits
    name = "".join(random.choice(fname_chars) for _ in range(20))

    # Import logic is version-dependent.
    if sys.version_info >= (3, 5):
        from importlib import util as _il_util
        modspec = _il_util.spec_from_file_location(
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


def is_null_like(x):
    """
    Determine whether an object is effectively null.

    :param object x: Object for which null likeness is to be determined.
    :return bool: Whether given object is effectively "null."
    """
    return x in [None, ""] or \
        (coll_like(x) and isinstance(x, Sized) and 0 == len(x))


def is_url(maybe_url):
    """
    Determine whether a path is a URL.

    :param str maybe_url: path to investigate as URL
    :return bool: whether path appears to be a URL
    """
    return urlparse(maybe_url).scheme != ""


def non_null_value(k, m):
    """
    Determine whether a mapping has a non-null value for a given key.

    :param Hashable k: Key to test for non-null value
    :param Mapping m: Mapping to test for non-null value for given key
    :return bool: Whether given mapping contains given key with non-null value
    """
    return k in m and not is_null_like(m[k])


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


def sample_folder(prj, sample):
    """
    Get the path to this Project's root folder for the given Sample.

    :param attmap.AttMap | Project prj: project with which sample is associated
    :param Mapping sample: Sample or sample data for which to get root output
        folder path.
    :return str: this Project's root folder for the given Sample
    """
    return os.path.join(prj.metadata.results_subdir,
                        sample["sample_name"])


@contextlib.contextmanager
def standard_stream_redirector(stream):
    """
    Temporarily redirect stdout and stderr to another stream.

    This can be useful for capturing messages for easier inspection, or
    for rerouting and essentially ignoring them, with the destination as
    something like an opened os.devnull.

    :param FileIO[str] stream: temporary proxy for standard streams
    """
    import sys
    genuine_stdout, genuine_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = stream, stream
    try:
        yield
    finally:
        sys.stdout, sys.stderr = genuine_stdout, genuine_stderr


def warn_derived_cols():
    """ Produce deprecation warning about derived columns. """
    _warn_cols_to_attrs("derived")


def warn_implied_cols():
    """ Produce deprecation warning about implied columns. """
    _warn_cols_to_attrs("implied")


def _warn_cols_to_attrs(prefix):
    """ Produce deprecation warning about 'columns' rather than 'attributes' """
    warnings.warn("{pfx}_columns should be encoded and referenced "
                  "as {pfx}_attributes".format(pfx=prefix), DeprecationWarning)



class CommandChecker(object):
    """
    Validate PATH availability of executables referenced by a config file.

    :param str path_conf_file: path to configuration file with
        sections detailing executable tools to validate
    :param Iterable[str] sections_to_check: names of
        sections of the given configuration file that are relevant;
        optional, will default to all sections if not given, but some
        may be excluded via another optional parameter
    :param Iterable[str] sections_to_skip: analogous to
        the check names parameter, but for specific sections to skip.

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
        _LOGGER.debug("Command '{0}' is not callable: {1}".
                      format(alias_value, command))
    return not bool(code)
