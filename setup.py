#!/usr/bin/env python

import sys, os
import shutil
from collections import defaultdict
try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup


setup_args = {}
install_requires = ['param>=1.8.0,<2.0', 'numpy>=1.0', 'pyviz_comms>=0.7.2']

extras_require = {}

# Notebook dependencies
extras_require['notebook'] = ['ipython>=5.4.0', 'notebook']

# IPython Notebook + pandas + matplotlib + bokeh
extras_require['recommended'] = extras_require['notebook'] + [
    'pandas', 'matplotlib>=2.1', 'bokeh>=1.1.0,<2.0.0', 'panel']

# Requirements to run all examples
extras_require['examples'] = extras_require['recommended'] + [
    'networkx', 'pillow', 'xarray>=0.10.4', 'plotly>=3.4',
    'datashader', 'selenium', 'phantomjs', 'ffmpeg', 'streamz>=0.5.0',
    'cftime', 'netcdf4', 'bzip2', 'dask', 'scipy']

# Extra third-party libraries
extras_require['extras'] = extras_require['examples']+[
    'cyordereddict', 'pscript==0.7.1']

# Test requirements
extras_require['tests'] = ['nose', 'flake8==3.6.0', 'coveralls', 'path.py', 'matplotlib>=2.1,<3.1']

extras_require['unit_tests'] = extras_require['examples']+extras_require['tests']

extras_require['basic_tests'] = extras_require['tests']+[
    'matplotlib>=2.1', 'bokeh>=1.1.0']+extras_require['notebook']

extras_require['nbtests'] = extras_require['recommended'] + [
    'nose', 'awscli', 'deepdiff', 'nbconvert==5.3.1', 'jsonschema==2.6.0',
    'cyordereddict', 'ipython==5.4.1']

extras_require['doc'] = extras_require['examples'] + [
    'nbsite>0.5.2', 'sphinx<2.0', 'sphinx_ioam_theme']

extras_require['build'] = ['param >=1.7.0', 'setuptools']

# Everything including cyordereddict (optimization) and nosetests
extras_require['all'] = list(set(extras_require['unit_tests']) | set(extras_require['nbtests']))


def embed_version(basepath, ref='v0.2.2'):
    """
    Autover is purely a build time dependency in all cases (conda and
    pip) except for when you use pip's remote git support [git+url] as
    1) you need a dynamically changing version and 2) the environment
    starts off clean with zero dependencies installed.
    This function acts as a fallback to make Version available until
    PEP518 is commonly supported by pip to express build dependencies.
    """
    import io, zipfile, importlib
    try:    from urllib.request import urlopen
    except: from urllib import urlopen
    try:
        url = 'https://github.com/ioam/autover/archive/{ref}.zip'
        response = urlopen(url.format(ref=ref))
        zf = zipfile.ZipFile(io.BytesIO(response.read()))
        ref = ref[1:] if ref.startswith('v') else ref
        embed_version = zf.read('autover-{ref}/autover/version.py'.format(ref=ref))
        with open(os.path.join(basepath, 'version.py'), 'wb') as f:
            f.write(embed_version)
        return importlib.import_module("version")
    except:
        return None

def get_setup_version(reponame):
    """
    Helper to get the current version from either git describe or the
    .version file (if available).
    """
    import json
    basepath = os.path.split(__file__)[0]
    version_file_path = os.path.join(basepath, reponame, '.version')
    try:
        from param import version

        # Ensure that param.version has Version object
        assert hasattr(version, 'Version')
    except:
        version = embed_version(basepath)
    if version is not None:
        return version.Version.setup_version(basepath, reponame, archive_commit="$Format:%h$")
    else:
        print("WARNING: param>=1.6.0 unavailable. If you are installing a package, this warning can safely be ignored. If you are creating a package or otherwise operating in a git repository, you should install param>=1.6.0.")
        return json.load(open(version_file_path, 'r'))['version_string']

setup_args.update(dict(
    name='holoviews',
    version=get_setup_version("holoviews"),
    python_requires=">=2.7",
    install_requires=install_requires,
    extras_require=extras_require,
    description='Stop plotting your data - annotate your data and let it visualize itself.',
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Jean-Luc Stevens and Philipp Rudiger",
    author_email="holoviews@gmail.com",
    maintainer="PyViz Developers",
    maintainer_email="developers@pyviz.org",
    platforms=['Windows', 'Mac OS X', 'Linux'],
    license='BSD',
    url='https://www.holoviews.org',
    entry_points={
        'console_scripts': [
            'holoviews = holoviews.util.command:main'
        ]},
    packages=["holoviews",
              "holoviews.core",
              "holoviews.core.data",
              "holoviews.element",
              "holoviews.ipython",
              "holoviews.util",
              "holoviews.operation",
              "holoviews.plotting",
              "holoviews.plotting.mpl",
              "holoviews.plotting.bokeh",
              "holoviews.plotting.plotly",
              "holoviews.tests",
              "holoviews.tests.core",
              "holoviews.tests.core.data",
              "holoviews.tests.element",
              "holoviews.tests.ipython",
              "holoviews.tests.ipython.notebooks",
              "holoviews.tests.operation",
              "holoviews.tests.plotting",
              "holoviews.tests.plotting.bokeh",
              "holoviews.tests.plotting.matplotlib",
              "holoviews.tests.plotting.plotly",
              "holoviews.tests.util"],
    package_data={'holoviews': ['.version'],
                  'holoviews.ipython': ['*.html'],
                  'holoviews.plotting.mpl': ['*.mplstyle'],
                  'holoviews.tests.ipython.notebooks': ['*.ipynb']},
    classifiers=[
        "License :: OSI Approved :: BSD License",
        "Development Status :: 5 - Production/Stable",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Operating System :: OS Independent",
        "Intended Audience :: Science/Research",
        "Intended Audience :: Developers",
        "Natural Language :: English",
        "Topic :: Scientific/Engineering",
        "Topic :: Software Development :: Libraries"]
))

def check_pseudo_package(path):
    """
    Verifies that a fake subpackage path for assets (notebooks, svgs,
    pngs etc) both exists and is populated with files.
    """
    if not os.path.isdir(path):
        raise Exception("Please make sure pseudo-package %s exists." % path)
    else:
        assets = os.listdir(path)
        if len(assets) == 0:
            raise Exception("Please make sure pseudo-package %s is populated." % path)


excludes = ['DS_Store', '.log', 'ipynb_checkpoints']
packages = []
extensions = defaultdict(list)

def walker(top, names):
    """
    Walks a directory and records all packages and file extensions.
    """
    global packages, extensions
    if any(exc in top for exc in excludes):
        return
    package = top[top.rfind('holoviews'):].replace(os.path.sep, '.')
    packages.append(package)
    for name in names:
        ext = '.'.join(name.split('.')[1:])
        ext_str = '*.%s' % ext
        if ext and ext not in excludes and ext_str not in extensions[package]:
            extensions[package].append(ext_str)


# Note: This function should be identical to util.examples
# (unfortunate and unavoidable duplication)
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
    ignore = shutil.ignore_patterns('.ipynb_checkpoints', '*.pyc', '*~')
    tree_root = os.path.abspath(example_dir)
    if os.path.isdir(tree_root):
        shutil.copytree(tree_root, path, ignore=ignore, symlinks=True)
    else:
        print('Cannot find %s' % tree_root)



def package_assets(example_path):
    """
    Generates pseudo-packages for the examples directory.
    """
    examples(example_path, force=True, root=__file__)
    for root, dirs, files in os.walk(example_path):
        walker(root, dirs+files)
    setup_args['packages'] += packages
    for p, exts in extensions.items():
        if exts:
            setup_args['package_data'][p] = exts


if __name__ == "__main__":
    example_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'holoviews/examples')
    if 'develop' not in sys.argv:
        package_assets(example_path)

    if 'install' in sys.argv:
        header = "HOLOVIEWS INSTALLATION INFORMATION"
        bars = "="*len(header)

        extras = '\n'.join('holoviews[%s]' % e for e in setup_args['extras_require'])

        print("%s\n%s\n%s" % (bars, header, bars))

        print("\nHoloViews supports the following installation types:\n")
        print("%s\n" % extras)
        print("Users should consider using one of these options.\n")
        print("By default only a core installation is performed and ")
        print("only the minimal set of dependencies are fetched.\n\n")
        print("For more information please visit http://holoviews.org/install.html\n")
        print(bars+'\n')

    setup(**setup_args)

    if os.path.isdir(example_path):
        shutil.rmtree(example_path)
