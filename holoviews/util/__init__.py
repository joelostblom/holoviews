import os, sys, inspect, shutil

from collections import defaultdict
from types import FunctionType

try:
    from pathlib import Path
except:
    Path = None

import param
from pyviz_comms import extension as _pyviz_extension

from ..core import DynamicMap, HoloMap, Dimensioned, ViewableElement, StoreOptions, Store
from ..core.options import options_policy, Keywords, Options
from ..core.operation import Operation
from ..core.util import basestring, merge_options_to_dict, OrderedDict
from ..core.operation import OperationCallable
from ..core.spaces import Callable
from ..core import util
from ..streams import Stream, Params
from .settings import OutputSettings, list_formats, list_backends

Store.output_settings = OutputSettings



def examples(path='holoviews-examples', verbose=False, force=False, root=__file__):
    """
    Copies the notebooks to the supplied path.
    """
    filepath = os.path.abspath(os.path.dirname(root))
    example_dir = os.path.join(filepath, './examples')
    if not os.path.exists(example_dir):
        example_dir = os.path.join(filepath, '../examples')
    if os.path.exists(path):
        if not force:
            print('%s directory already exists, either delete it or set the force flag' % path)
            return
        shutil.rmtree(path)
    ignore = shutil.ignore_patterns('.ipynb_checkpoints','*.pyc','*~')
    tree_root = os.path.abspath(example_dir)
    if os.path.isdir(tree_root):
        shutil.copytree(tree_root, path, ignore=ignore, symlinks=True)
    else:
        print('Cannot find %s' % tree_root)



class opts(param.ParameterizedFunction):
    """
    Utility function to set options at the global level or to provide an
    Options object that can be used with the .options method of an
    element or container.

    Option objects can be generated and validated in a tab-completable
    way (in appropriate environments such as Jupyter notebooks) using
    completers such as opts.Curve, opts.Image, opts.Overlay, etc.

    To set opts globally you can pass these option objects into opts.defaults:

    opts.defaults(*options)

    For instance:

    opts.defaults(opts.Curve(color='red'))

    To set opts on a specific object, you can supply these option
    objects to the .options method.

    For instance:

    curve = hv.Curve([1,2,3])
    curve.options(opts.Curve(color='red'))

    The options method also accepts lists of Option objects.
    """

    __original_docstring__ = None

    # Keywords not to be tab-completed (helps with deprecation)
    _no_completion = ['title_format', 'color_index', 'size_index', 'finalize_hooks',
                      'scaling_factor', 'scaling_method', 'size_fn', 'normalize_lengths',
                      'group_index', 'category_index', 'stack_index', 'color_by']

    strict = param.Boolean(default=False, doc="""
       Whether to be strict about the options specification. If not set
       to strict (default), any invalid keywords are simply skipped. If
       strict, invalid keywords prevent the options being applied.""")

    def __call__(self, *args, **params):
        if not params and not args:
            return Options()
        elif params and not args:
            return Options(**params)

        if len(args) == 1:
            msg = ("Positional argument signature of opts is deprecated, "
                   "use opts.defaults instead.\nFor instance, instead of "
                   "opts('Points (size=5)') use opts.defaults(opts.Points(size=5))")
            if util.config.future_deprecations:
                self.param.warning(msg)
            self._linemagic(args[0])
        elif len(args) == 2:
            msg = ("Double positional argument signature of opts is deprecated, "
                   "use the .options method instead.\nFor instance, instead of "
                   "opts('Points (size=5)', points) use points.options(opts.Points(size=5))")

            if util.config.future_deprecations:
                self.param.warning(msg)

            self._cellmagic(args[0], args[1])


    @classmethod
    def _group_kwargs_to_options(cls, obj, kwargs):
        "Format option group kwargs into canonical options format"
        groups = Options._option_groups
        if set(kwargs.keys()) - set(groups):
            raise Exception("Keyword options %s must be one of  %s" % (groups,
                            ','.join(repr(g) for g in groups)))
        elif not all(isinstance(v, dict) for v in kwargs.values()):
            raise Exception("The %s options must be specified using dictionary groups" %
                            ','.join(repr(k) for k in kwargs.keys()))

        # Check whether the user is specifying targets (such as 'Image.Foo')
        targets = [grp and all(k[0].isupper() for k in grp) for grp in kwargs.values()]
        if any(targets) and not all(targets):
            raise Exception("Cannot mix target specification keys such as 'Image' with non-target keywords.")
        elif not any(targets):
            # Not targets specified - add current object as target
            sanitized_group = util.group_sanitizer(obj.group)
            if obj.label:
                identifier = ('%s.%s.%s' % (
                    obj.__class__.__name__, sanitized_group,
                    util.label_sanitizer(obj.label)))
            elif  sanitized_group != obj.__class__.__name__:
                identifier = '%s.%s' % (obj.__class__.__name__, sanitized_group)
            else:
                identifier = obj.__class__.__name__

            options = {identifier:{grp:kws for (grp,kws) in kwargs.items()}}
        else:
            dfltdict = defaultdict(dict)
            for grp, entries in kwargs.items():
                for identifier, kws in entries.items():
                    dfltdict[identifier][grp] = kws
            options = dict(dfltdict)
        return options

    @classmethod
    def _apply_groups_to_backend(cls, obj, options, backend, clone):
        "Apply the groups to a single specified backend"
        obj_handle = obj
        if options is None:
            if clone:
                obj_handle = obj.map(lambda x: x.clone(id=None))
            else:
                obj.map(lambda x: setattr(x, 'id', None))
        elif clone:
            obj_handle = obj.map(lambda x: x.clone(id=x.id))

        return StoreOptions.set_options(obj_handle, options, backend=backend)


    @classmethod
    def _grouped_backends(cls, options, backend):
        "Group options by backend and filter out output group appropriately"

        if options is None:
            return [(backend or Store.current_backend, options)]
        dfltdict = defaultdict(dict)
        for spec, groups in options.items():
            if 'output' not in groups.keys() or len(groups['output'])==0:
                dfltdict[backend or Store.current_backend][spec.strip()] = groups
            elif set(groups['output'].keys()) - set(['backend']):
                dfltdict[groups['output']['backend']][spec.strip()] = groups
            elif ['backend'] == list(groups['output'].keys()):
                filtered = {k:v for k,v in groups.items() if k != 'output'}
                dfltdict[groups['output']['backend']][spec.strip()] = filtered
            else:
                raise Exception('The output options group must have the backend keyword')

        return [(bk, bk_opts) for (bk, bk_opts) in dfltdict.items()]

    @classmethod
    def apply_groups(cls, obj, options=None, backend=None, clone=True, **kwargs):
        """Applies nested options definition grouped by type.

        Applies options on an object or nested group of objects,
        returning a new object with the options applied. This method
        accepts the separate option namespaces explicitly (i.e 'plot',
        'style' and 'norm').

        If the options are to be set directly on the object a
        simple format may be used, e.g.:

            opts.apply_groups(obj, style={'cmap': 'viridis'},
                                         plot={'show_title': False})

        If the object is nested the options must be qualified using
        a type[.group][.label] specification, e.g.:

            opts.apply_groups(obj, {'Image': {'plot':  {'show_title': False},
                                              'style': {'cmap': 'viridis}}})

        If no opts are supplied all options on the object will be reset.

        Args:
            options (dict): Options specification
                Options specification should be indexed by
                type[.group][.label] or option type ('plot', 'style',
                'norm').
            backend (optional): Backend to apply options to
                Defaults to current selected backend
            clone (bool, optional): Whether to clone object
                Options can be applied inplace with clone=False
            **kwargs: Keywords of options by type
                Applies options directly to the object by type
                (e.g. 'plot', 'style', 'norm') specified as
                dictionaries.

        Returns:
            Returns the object or a clone with the options applied
        """
        if isinstance(options, basestring):
            from ..util.parser import OptsSpec
            try:
                options = OptsSpec.parse(options)
            except SyntaxError:
                options = OptsSpec.parse(
                    '{clsname} {options}'.format(clsname=obj.__class__.__name__,
                                                 options=options))
        if kwargs:
            options = cls._group_kwargs_to_options(obj, kwargs)

        for backend, backend_opts in cls._grouped_backends(options, backend):
            obj = cls._apply_groups_to_backend(obj, backend_opts, backend, clone)
        return obj

    @classmethod
    def _process_magic(cls, options, strict, backends=None):
        if isinstance(options, basestring):
            from .parser import OptsSpec
            try:     ns = get_ipython().user_ns  # noqa
            except:  ns = globals()
            options = OptsSpec.parse(options, ns=ns)

        errmsg = StoreOptions.validation_error_message(options, backends=backends)
        if errmsg:
            sys.stderr.write(errmsg)
            if strict:
                sys.stderr.write('Options specification will not be applied.')
                return options, True
        return options, False

    @classmethod
    def _cellmagic(cls, options, obj, strict=False):
        "Deprecated, not expected to be used by any current code"
        options, failure = cls._process_magic(options, strict)
        if failure: return obj
        if not isinstance(obj, Dimensioned):
            return obj
        else:
            return StoreOptions.set_options(obj, options)

    @classmethod
    def _linemagic(cls, options, strict=False, backend=None):
        "Deprecated, not expected to be used by any current code"
        backends = None if backend is None else [backend]
        options, failure = cls._process_magic(options, strict, backends=backends)
        if failure: return
        with options_policy(skip_invalid=True, warn_on_skip=False):
            StoreOptions.apply_customizations(options, Store.options(backend=backend))


    @classmethod
    def defaults(cls, *options, **kwargs):
        """Set default options for a session.

        Set default options for a session. whether in a Python script or
        a Jupyter notebook.

        Args:
           *options: Option objects used to specify the defaults.
           backend:  The plotting extension the options apply to
        """
        if kwargs and len(kwargs) != 1 and list(kwargs.keys())[0] != 'backend':
            raise Exception('opts.defaults only accepts "backend" keyword argument')

        cls._linemagic(cls._expand_options(merge_options_to_dict(options)), backend=kwargs.get('backend'))


    @classmethod
    def _expand_by_backend(cls, options, backend):
        """
        Given a list of flat Option objects which may or may not have
        'backend' in their kwargs, return a list of grouped backend
        """
        groups = defaultdict(list)
        used_fallback = False
        for obj in options:
            if 'backend' in obj.kwargs:
                opts_backend = obj.kwargs['backend']
            elif backend is None:
                opts_backend = Store.current_backend
                obj.kwargs['backend']= opts_backend
            else:
                opts_backend = backend
                obj.kwargs['backend'] = opts_backend
                used_fallback = True
            groups[opts_backend].append(obj)

        if backend and not used_fallback:
            cls.param.warning("All supplied Options objects already define a backend, "
                              "backend override %r will be ignored." % backend)

        return [(bk, cls._expand_options(o, bk)) for (bk, o) in groups.items()]

    @classmethod
    def _expand_options(cls, options, backend=None):
        """
        Validates and expands a dictionaries of options indexed by
        type[.group][.label] keys into separate style, plot, norm and
        output options.

            opts._expand_options({'Image': dict(cmap='viridis', show_title=False)})

        returns

            {'Image': {'plot': dict(show_title=False), 'style': dict(cmap='viridis')}}
        """
        current_backend = Store.current_backend
        try:
            backend_options = Store.options(backend=backend or current_backend)
        except KeyError as e:
            raise Exception('The %s backend is not loaded. Please load the backend using hv.extension.' % str(e))
        expanded = {}
        if isinstance(options, list):
            options = merge_options_to_dict(options)

        for objspec, options in options.items():
            objtype = objspec.split('.')[0]
            if objtype not in backend_options:
                raise ValueError('%s type not found, could not apply options.'
                                 % objtype)
            obj_options = backend_options[objtype]
            expanded[objspec] = {g: {} for g in obj_options.groups}
            for opt, value in options.items():
                found = False
                valid_options = []
                for g, group_opts in sorted(obj_options.groups.items()):
                    if opt in group_opts.allowed_keywords:
                        expanded[objspec][g][opt] = value
                        found = True
                        break
                    valid_options += group_opts.allowed_keywords
                if found: continue
                cls._options_error(opt, objtype, backend, valid_options)
        return expanded


    @classmethod
    def _options_error(cls, opt, objtype, backend, valid_options):
        """
        Generates an error message for an invalid option suggesting
        similar options through fuzzy matching.
        """
        current_backend = Store.current_backend
        loaded_backends = Store.loaded_backends()
        kws = Keywords(values=valid_options)
        matches = sorted(kws.fuzzy_match(opt))
        if backend is not None:
            if matches:
                raise ValueError('Unexpected option %r for %s type '
                                 'when using the %r extension. Similar '
                                 'options are: %s.' %
                                 (opt, objtype, backend, matches))
            else:
                raise ValueError('Unexpected option %r for %s type '
                                 'when using the %r extension. No '
                                 'similar options founds.' %
                                 (opt, objtype, backend))

        # Check option is invalid for all backends
        found = []
        for lb in [b for b in loaded_backends if b != backend]:
            lb_options = Store.options(backend=lb).get(objtype)
            if lb_options is None:
                continue
            for g, group_opts in lb_options.groups.items():
                if opt in group_opts.allowed_keywords:
                    found.append(lb)
        if found:
            param.main.param.warning(
                'Option %r for %s type not valid for selected '
                'backend (%r). Option only applies to following '
                'backends: %r' % (opt, objtype, current_backend, found))
            return

        if matches:
            raise ValueError('Unexpected option %r for %s type '
                             'across all extensions. Similar options '
                             'for current extension (%r) are: %s.' %
                             (opt, objtype, current_backend, matches))
        else:
            raise ValueError('Unexpected option %r for %s type '
                             'across all extensions. No similar options '
                             'found.' % (opt, objtype))

    @classmethod
    def _builder_reprs(cls, options, namespace=None, ns=None):
        """
        Given a list of Option objects (such as those returned from
        OptsSpec.parse_options) or an %opts or %%opts magic string,
        return a list of corresponding option builder reprs. The
        namespace is typically given as 'hv' if fully qualified
        namespaces are desired.
        """
        if isinstance(options, basestring):
            from .parser import OptsSpec
            if ns is None:
                try:     ns = get_ipython().user_ns  # noqa
                except:  ns = globals()
            options = options.replace('%%opts','').replace('%opts','')
            options = OptsSpec.parse_options(options, ns=ns)


        reprs = []
        ns = '{namespace}.'.format(namespace=namespace) if namespace else ''
        for option in options:
            kws = ', '.join('%s=%r' % (k,option.kwargs[k]) for k in sorted(option.kwargs))
            if '.' in option.key:
                element = option.key.split('.')[0]
                spec = repr('.'.join(option.key.split('.')[1:])) + ', '
            else:
                element = option.key
                spec = ''

            opts_format = '{ns}opts.{element}({spec}{kws})'
            reprs.append(opts_format.format(ns=ns, spec=spec, kws=kws, element=element))
        return reprs

    @classmethod
    def _create_builder(cls, element, completions):
        def builder(cls, spec=None, **kws):
            spec = element if spec is None else '%s.%s' % (element, spec)
            prefix = 'In opts.{element}(...), '.format(element=element)
            backend = kws.get('backend', None)
            keys = set(kws.keys())
            if backend:
                allowed_kws = cls._element_keywords(backend,
                                                    elements=[element])[element]
                invalid = keys - set(allowed_kws)
            else:
                mismatched = {}
                all_valid_kws =  set()
                for loaded_backend in Store.loaded_backends():
                    valid = set(cls._element_keywords(loaded_backend).get(element, []))
                    all_valid_kws |= set(valid)
                    if keys <= valid: # Found a backend for which all keys are valid
                        return Options(spec, **kws)
                    mismatched[loaded_backend] = list(keys - valid)

                invalid =  keys - all_valid_kws # Keys not found for any backend
                if mismatched and not invalid:  # Keys found across multiple backends
                    msg = ('{prefix} keywords supplied are mixed across backends. '
                           'Keyword(s) {info}')
                    info = ', '.join('%s are invalid for %s'
                                     % (', '.join(repr(el) for el in v), k)
                                     for k,v in mismatched.items())
                    raise ValueError(msg.format(info=info, prefix=prefix))
                allowed_kws = completions

            reraise = False
            if invalid:
                try:
                    cls._options_error(list(invalid)[0], element, backend, allowed_kws)
                except ValueError as e:
                    msg = str(e)[0].lower() + str(e)[1:]
                    reraise = True

                if reraise:
                    raise ValueError(prefix + msg)

            return Options(spec, **kws)

        filtered_keywords = [k for k in completions if k not in cls._no_completion]
        kws = ', '.join('{opt}=None'.format(opt=opt) for opt in sorted(filtered_keywords))
        builder.__doc__ = '{element}({kws})'.format(element=element, kws=kws)
        return classmethod(builder)


    @classmethod
    def _element_keywords(cls, backend, elements=None):
        "Returns a dictionary of element names to allowed keywords"
        if backend not in Store.loaded_backends():
            return {}

        mapping = {}
        backend_options = Store.options(backend)
        elements = elements if elements is not None else backend_options.keys()
        for element in elements:
            if '.' in element: continue
            element = element if isinstance(element, tuple) else (element,)
            element_keywords = []
            options = backend_options['.'.join(element)]
            for group in Options._option_groups:
                element_keywords.extend(options[group].allowed_keywords)

            mapping[element[0]] = element_keywords
        return mapping


    @classmethod
    def _update_backend(cls, backend):

        if cls.__original_docstring__ is None:
            cls.__original_docstring__ = cls.__doc__

        all_keywords = set()
        element_keywords = cls._element_keywords(backend)
        for element, keywords in element_keywords.items():
            with param.logging_level('CRITICAL'):
                all_keywords |= set(keywords)
                setattr(cls, element,
                        cls._create_builder(element, keywords))

        filtered_keywords = [k for k in all_keywords if k not in cls._no_completion]
        kws = ', '.join('{opt}=None'.format(opt=opt) for opt in sorted(filtered_keywords))
        old_doc = cls.__original_docstring__.replace('params(strict=Boolean, name=String)','')
        cls.__doc__ = '\n    opts({kws})'.format(kws=kws) + old_doc


Store._backend_switch_hooks.append(opts._update_backend)


class output(param.ParameterizedFunction):
    """
    Utility function to set output either at the global level or on a
    specific object.

    To set output globally use:

    output(options)

    Where options may be an options specification string (as accepted by
    the IPython opts magic) or an options specifications dictionary.

    For instance:

    output("backend='bokeh'") # Or equivalently
    output(backend='bokeh')

    To set save output from a specific object do disk using the
    'filename' argument, you can supply the object as the first
    positional argument and supply the filename keyword:

    curve = hv.Curve([1,2,3])
    output(curve, filename='curve.png')

    For compatibility with the output magic, you can supply the object
    as the second argument after the string specification:

    curve = hv.Curve([1,2,3])
    output("filename='curve.png'", curve)

    These two modes are equivalent to the IPython output line magic and
    the cell magic respectively.
    """

    @classmethod
    def info(cls):
        deprecate = ['filename', 'info', 'mode']
        options = Store.output_settings.options
        defaults = Store.output_settings.defaults
        keys = [k for k,v in options.items() if k not in deprecate and v != defaults[k]]
        pairs = {k:options[k] for k in sorted(keys)}
        if 'backend' not in keys:
            pairs['backend'] = Store.current_backend
        if ':' in pairs['backend']:
            pairs['backend'] = pairs['backend'].split(':')[0]

        keywords = ', '.join('%s=%r' % (k,pairs[k]) for k in sorted(pairs.keys()))
        print('output({kws})'.format(kws=keywords))


    def __call__(self, *args, **options):
        help_prompt = 'For help with hv.util.output call help(hv.util.output)'
        line, obj = None,None
        if len(args) > 2:
            raise TypeError('The opts utility accepts one or two positional arguments.')
        if len(args) == 1 and not isinstance(args[0], basestring):
            obj = args[0]
        elif len(args) == 1:
            line = args[0]
        elif len(args) == 2:
            (line, obj) = args

        if isinstance(obj, Dimensioned):
            if line:
                options = Store.output_settings.extract_keywords(line, {})
            for k in options.keys():
                if k not in Store.output_settings.allowed:
                    raise KeyError('Invalid keyword: %s' % k)
            if 'filename' in options:
                if util.config.future_deprecations:
                    self.param.warning('The filename argument of output is deprecated. '
                                       'Use hv.save instead.')

            def display_fn(obj, renderer):
                try:
                    from IPython.display import display
                except:
                    return
                display(obj)

            Store.output_settings.output(line=line, cell=obj, cell_runner=display_fn,
                                         help_prompt=help_prompt, **options)
        elif obj is not None:
            return obj
        else:
            Store.output_settings.output(line=line, help_prompt=help_prompt, **options)

output.__doc__ = Store.output_settings._generate_docstring()


def renderer(name):
    """
    Helper utility to access the active renderer for a given extension.
    """
    try:
        if name not in Store.renderers:
            extension(name)
        return Store.renderers[name]
    except ImportError:
        msg = ('Could not find a {name!r} renderer, available renderers are: {available}.')
        available = ', '.join(repr(k) for k in Store.renderers)
        raise ImportError(msg.format(name=name, available=available))


class extension(_pyviz_extension):
    """
    Helper utility used to load holoviews extensions. These can be
    plotting extensions, element extensions or anything else that can be
    registered to work with HoloViews.
    """

    # Mapping between backend name and module name
    _backends = {'matplotlib': 'mpl',
                 'bokeh': 'bokeh',
                 'plotly': 'plotly'}

    # Hooks run when a backend is loaded
    _backend_hooks = defaultdict(list)

    def __call__(self, *args, **params):
        # Get requested backends
        config = params.pop('config', {})
        util.config.param.set_param(**config)
        imports = [(arg, self._backends[arg]) for arg in args
                   if arg in self._backends]
        for p, val in sorted(params.items()):
            if p in self._backends:
                imports.append((p, self._backends[p]))
        if not imports:
            args = ['matplotlib']
            imports = [('matplotlib', 'mpl')]

        args = list(args)
        selected_backend = None
        for backend, imp in imports:
            try:
                __import__(backend)
            except:
                self.param.warning("%s could not be imported, ensure %s is installed."
                             % (backend, backend))
            try:
                __import__('holoviews.plotting.%s' % imp)
                if selected_backend is None:
                    selected_backend = backend
            except util.VersionError as e:
                self.param.warning(
                    "HoloViews %s extension could not be loaded. "
                    "The installed %s version %s is less than "
                    "the required version %s." %
                    (backend, backend, e.version, e.min_version))
            except Exception as e:
                self.param.warning(
                    "Holoviews %s extension could not be imported, "
                    "it raised the following exception: %s('%s')" %
                    (backend, type(e).__name__, e))
            finally:
                Store.output_settings.allowed['backend'] = list_backends()
                Store.output_settings.allowed['fig'] = list_formats('fig', backend)
                Store.output_settings.allowed['holomap'] = list_formats('holomap', backend)
            for hook in self._backend_hooks[backend]:
                try:
                    hook()
                except Exception as e:
                    self.param.warning('%s backend hook %s failed with '
                                       'following exception: %s' %
                                       (backend, hook, e))

        if selected_backend is None:
            raise ImportError('None of the backends could be imported')
        Store.set_current_backend(selected_backend)

    @classmethod
    def register_backend_callback(cls, backend, callback):
        """Registers a hook which is run when a backend is loaded"""
        cls._backend_hooks[backend].append(callback)


def save(obj, filename, fmt='auto', backend=None, resources='cdn', **kwargs):
    """
    Saves the supplied object to file.

    The available output formats depend on the backend being used. By
    default and if the filename is a string the output format will be
    inferred from the file extension. Otherwise an explicit format
    will need to be specified. For ambiguous file extensions such as
    html it may be necessary to specify an explicit fmt to override
    the default, e.g. in the case of 'html' output the widgets will
    default to fmt='widgets', which may be changed to scrubber widgets
    using fmt='scrubber'.

    Arguments
    ---------
    obj: HoloViews object
        The HoloViews object to save to file
    filename: string or IO object
        The filename or BytesIO/StringIO object to save to
    fmt: string
        The format to save the object as, e.g. png, svg, html, or gif
        and if widgets are desired either 'widgets' or 'scrubber'
    backend: string
        A valid HoloViews rendering backend, e.g. bokeh or matplotlib
    resources: string or bokeh.resource.Resources
        Bokeh resources used to load bokehJS components. Defaults to
        CDN, to embed resources inline for offline usage use 'inline'
        or bokeh.resources.INLINE.
    **kwargs: dict
        Additional keyword arguments passed to the renderer,
        e.g. fps for animations
    """
    backend = backend or Store.current_backend
    renderer_obj = renderer(backend)
    if kwargs:
        renderer_obj = renderer_obj.instance(**kwargs)
    if Path is not None and isinstance(filename, Path):
        filename = str(filename.absolute())
    if isinstance(filename, basestring):
        supported = [mfmt for tformats in renderer_obj.mode_formats.values()
                     for mformats in tformats.values() for mfmt in mformats]
        formats = filename.split('.')
        if fmt == 'auto' and formats and formats[-1] != 'html':
            fmt = formats[-1]
        if formats[-1] in supported:
            filename = '.'.join(formats[:-1])
    return renderer_obj.save(obj, filename, fmt=fmt, resources=resources)


def render(obj, backend=None, **kwargs):
    """
    Renders the HoloViews object to the corresponding object in the
    specified backend, e.g. a Matplotlib or Bokeh figure.

    The backend defaults to the currently declared default
    backend. The resulting object can then be used with other objects
    in the specified backend. For instance, if you want to make a
    multi-part Bokeh figure using a plot type only available in
    HoloViews, you can use this function to return a Bokeh figure that
    you can use like any hand-constructed Bokeh figure in a Bokeh
    layout.

    Arguments
    ---------
    obj: HoloViews object
        The HoloViews object to render
    backend: string
        A valid HoloViews rendering backend
    **kwargs: dict
        Additional keyword arguments passed to the renderer,
        e.g. fps for animations

    Returns
    -------
    renderered:
        The rendered representation of the HoloViews object, e.g.
        if backend='matplotlib' a matplotlib Figure or FuncAnimation
    """
    backend = backend or Store.current_backend
    renderer_obj = renderer(backend)
    if kwargs:
        renderer_obj = renderer_obj.instance(**kwargs)
    plot = renderer_obj.get_plot(obj)
    if backend == 'matplotlib' and len(plot) > 1:
        return plot.anim(fps=renderer_obj.fps)
    return renderer_obj.get_plot(obj).state


class Dynamic(param.ParameterizedFunction):
    """
    Dynamically applies a callable to the Elements in any HoloViews
    object. Will return a DynamicMap wrapping the original map object,
    which will lazily evaluate when a key is requested. By default
    Dynamic applies a no-op, making it useful for converting HoloMaps
    to a DynamicMap.

    Any supplied kwargs will be passed to the callable and any streams
    will be instantiated on the returned DynamicMap. If the supplied
    operation is a method on a parameterized object which was
    decorated with parameter dependencies Dynamic will automatically
    create a stream to watch the parameter changes. This default
    behavior may be disabled by setting watch=False.
    """

    operation = param.Callable(default=lambda x: x, doc="""
        Operation or user-defined callable to apply dynamically""")

    kwargs = param.Dict(default={}, doc="""
        Keyword arguments passed to the function.""")

    link_inputs = param.Boolean(default=True, doc="""
         If Dynamic is applied to another DynamicMap, determines whether
         linked streams attached to its Callable inputs are
         transferred to the output of the utility.

         For example if the Dynamic utility is applied to a DynamicMap
         with an RangeXY, this switch determines whether the
         corresponding visualization should update this stream with
         range changes originating from the newly generated axes.""")

    shared_data = param.Boolean(default=False, doc="""
        Whether the cloned DynamicMap will share the same cache.""")

    streams = param.List(default=[], doc="""
        List of streams to attach to the returned DynamicMap""")

    def __call__(self, map_obj, **params):
        watch = params.pop('watch', True)
        self.p = param.ParamOverrides(self, params)
        callback = self._dynamic_operation(map_obj)
        streams = self._get_streams(map_obj, watch)
        if isinstance(map_obj, DynamicMap):
            dmap = map_obj.clone(callback=callback, shared_data=self.p.shared_data,
                                 streams=streams)
            if self.p.shared_data:
                dmap.data = OrderedDict([(k, callback.callable(*k))
                                          for k, v in dmap.data])
        else:
            dmap = self._make_dynamic(map_obj, callback, streams)
        return dmap


    def _get_streams(self, map_obj, watch=True):
        """
        Generates a list of streams to attach to the returned DynamicMap.
        If the input is a DynamicMap any streams that are supplying values
        for the key dimension of the input are inherited. And the list
        of supplied stream classes and instances are processed and
        added to the list.
        """
        streams = []
        op = self.p.operation
        for stream in self.p.streams:
            if inspect.isclass(stream) and issubclass(stream, Stream):
                stream = stream()
            elif not (isinstance(stream, Stream) or util.is_param_method(stream)):
                raise ValueError('Streams must be Stream classes or instances, found %s type' %
                                 type(stream).__name__)
            if isinstance(op, Operation):
                updates = {k: op.p.get(k) for k, v in stream.contents.items()
                           if v is None and k in op.p}
                if updates:
                    reverse = {v: k for k, v in stream._rename.items()}
                    stream.update(**{reverse.get(k, k): v for k, v in updates.items()})
            streams.append(stream)

        params = {k: v for k, v in self.p.kwargs.items() if isinstance(v, param.Parameter)
                  and isinstance(v.owner, param.Parameterized)}
        streams += Params.from_params(params)

        # Inherit dimensioned streams
        if isinstance(map_obj, DynamicMap):
            dim_streams = util.dimensioned_streams(map_obj)
            streams = list(util.unique_iterator(streams + dim_streams))

        # If callback is a parameterized method and watch is disabled add as stream
        has_dependencies = (util.is_param_method(op, has_deps=True) or
                            isinstance(op, FunctionType) and hasattr(op, '_dinfo'))
        if has_dependencies and watch:
            streams.append(op)

        # Add any keyword arguments which are parameterized methods
        # with dependencies as streams
        for value in self.p.kwargs.values():
            if util.is_param_method(value, has_deps=True):
                streams.append(value)

        valid, invalid = Stream._process_streams(streams)
        if invalid:
            msg = ('The supplied streams list contains objects that '
                   'are not Stream instances: {objs}')
            raise TypeError(msg.format(objs = ', '.join('%r' % el for el in invalid)))
        return valid

    def _process(self, element, key=None, kwargs={}):
        if util.is_param_method(self.p.operation) and util.get_method_owner(self.p.operation) is element:
            return self.p.operation(**kwargs)
        elif isinstance(self.p.operation, Operation):
            kwargs = {k: v for k, v in kwargs.items() if k in self.p.operation.param}
            return self.p.operation.process_element(element, key, **kwargs)
        else:
            return self.p.operation(element, **kwargs)

    def _eval_kwargs(self):
        """Evaluates any parameterized methods in the kwargs"""
        evaled_kwargs = {}
        for k, v in self.p.kwargs.items():
            if util.is_param_method(v):
                v = v()
            evaled_kwargs[k] = v
        return evaled_kwargs

    def _dynamic_operation(self, map_obj):
        """
        Generate function to dynamically apply the operation.
        Wraps an existing HoloMap or DynamicMap.
        """
        if not isinstance(map_obj, DynamicMap):
            def dynamic_operation(*key, **kwargs):
                kwargs = dict(self._eval_kwargs(), **kwargs)
                obj = map_obj[key] if isinstance(map_obj, HoloMap) else map_obj
                return self._process(obj, key, kwargs)
        else:
            def dynamic_operation(*key, **kwargs):
                kwargs = dict(self._eval_kwargs(), **kwargs)
                if map_obj._posarg_keys and not key:
                    key = tuple(kwargs[k] for k in map_obj._posarg_keys)
                return self._process(map_obj[key], key, kwargs)
        if isinstance(self.p.operation, Operation):
            return OperationCallable(dynamic_operation, inputs=[map_obj],
                                     link_inputs=self.p.link_inputs,
                                     operation=self.p.operation)
        else:
            return Callable(dynamic_operation, inputs=[map_obj],
                            link_inputs=self.p.link_inputs)


    def _make_dynamic(self, hmap, dynamic_fn, streams):
        """
        Accepts a HoloMap and a dynamic callback function creating
        an equivalent DynamicMap from the HoloMap.
        """
        if isinstance(hmap, ViewableElement):
            return DynamicMap(dynamic_fn, streams=streams)
        dim_values = zip(*hmap.data.keys())
        params = util.get_param_values(hmap)
        kdims = [d(values=list(util.unique_iterator(values))) for d, values in
                 zip(hmap.kdims, dim_values)]
        return DynamicMap(dynamic_fn, streams=streams, **dict(params, kdims=kdims))
