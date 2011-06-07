
import os
import hashlib

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

from ConfigParser import RawConfigParser, NoSectionError, NoOptionError

from django import template
from django.conf import settings
from django.utils.importlib import import_module
 

def get_merged_config(**options):
    """Get the final merged configuration for supvervisord, as a StringIO.

    This is the top-level function exported by this module.  It collects
    the various config files from installed applications and the main project,
    combines them together based on prioerity, and returns the resulting
    configuration as a readable StringIO object.
    """
    #  Find and load the containing project module.
    #  This is assumed to be the top-level package containing settings module.
    #  If it doesn't contain a manage.py script, we're in trouble.
    projname = settings.SETTINGS_MODULE.split(".",1)[0]
    projmod = import_module(projname)
    projdir = os.path.dirname(projmod.__file__)
    if not os.path.isfile(os.path.join(projdir,"manage.py")):
        msg = "Project %s doesn't have a ./manage.py" % (projname,)
        raise RuntimeError(msg)
    #  Start from the default configuration options.
    data = render_config(DEFAULT_CONFIG,projmod)
    merged_cfg = RawConfigParser()
    merged_cfg.readfp(StringIO(data))
    #  Add in each app-specific file as we find it.
    for data in find_app_configs(projmod):
        merged_cfg.readfp(StringIO(data))
    #  And add in the project-specific config file.
    projcfg = os.path.join(projdir,"supervisord.conf")
    if os.path.isfile(projcfg):
        with open(projcfg,"r") as f:
            data = render_config(f.read(),projmod)
        merged_cfg.readfp(StringIO(data))
    #  Process any default options.
    #     TODO 
    #  Add in the options specified on the command-line.
    merged_cfg.readfp(StringIO(get_config_from_options(**options)))
    #  Make sure we've got a port configured for supervisorctl to
    #  talk to supervisord.  It's passworded based on secret key.
    #  If they have configured a unix socket then use that, otherwise
    #  use an inet server on localhost at fixed-but-randomish port.
    username = hashlib.md5(settings.SECRET_KEY).hexdigest()
    password = hashlib.md5(username).hexdigest()
    if merged_cfg.has_section("unix_http_server"):
        set_if_missing(merged_cfg,"unix_http_server","username",username)
        set_if_missing(merged_cfg,"unix_http_server","password",password)
        serverurl = "unix://" + merged_cfg.get("unix_http_server","file")
    else:
        port = int(hashlib.md5(password).hexdigest()[:3],16) % 1000
        addr = "127.0.0.1:9%03d" % (port,)
        set_if_missing(merged_cfg,"inet_http_server","port",addr)
        set_if_missing(merged_cfg,"inet_http_server","username",username)
        set_if_missing(merged_cfg,"inet_http_server","password",password)
        serverurl = "http://" + merged_cfg.get("inet_http_server","port")
    set_if_missing(merged_cfg,"supervisorctl","serverurl",serverurl)
    set_if_missing(merged_cfg,"supervisorctl","username",username)
    set_if_missing(merged_cfg,"supervisorctl","password",password)
    set_if_missing(merged_cfg,"rpcinterface:supervisor",
                              "supervisor.rpcinterface_factory",
                              "supervisor.rpcinterface:make_main_rpcinterface")
    #  Write it out to a StringIO
    s = StringIO()
    merged_cfg.write(s)
    s.seek(0)
    print s.getvalue()
    return s


def render_config(data,proj,app=None):
    """Render the given config data using Django's template system.

    This function takes a config data string, project module, and optional
    app module, and loads the config data by rendering with Django's template
    system.  The template context will get the following variables:

        PROJECT_DIR:  directory containing the main Django project
        APP_DIR:      directory containing the specific app, if given
        settings:     the Django settings module
        environ:      the os.environ dict 

    """
    t = template.Template(data)
    c = template.Context({
        "PROJECT_DIR": os.path.dirname(proj.__file__),
        "APP_DIR": None if app is None else os.path.dirname(app.__file__),
        "settings": settings,
        "environ": os.environ,
    })
    return t.render(c).encode("ascii")


def find_app_configs(projmod):
    """Generator yielding app-provided config file data.

    This function searches for supervisord config files within each of the
    installed apps, in the order they are listed in INSTALLED_APPS.  Each
    file found is rendered and the resulting contents yielded as a string.
    """
    contrib_dir = os.path.join(os.path.dirname(__file__),"contrib")
    for appname in settings.INSTALLED_APPS:
        #  Look inside the djsupervisor contrib directory
        appfile = os.path.join(contrib_dir,appname.replace(".",os.sep))
        appfile = os.path.join(appfile,"supervisord.conf")
        if os.path.isfile(appfile):
            with open(appfile,"r") as f:
                yield render_config(f.read(),projmod,appmod)
        #  Look inside app managmenet directory
        appmod = import_module(appname)
        if not hasattr(appmod,"__file__"):
            continue
        appfile = os.path.join(os.path.dirname(appmod.__file__),"management")
        appfile = os.path.join(appfile,"supervisord.conf")
        if os.path.isfile(appfile):
            with open(appfile,"r") as f:
                yield render_config(f.read(),projmod,appmod)


def get_config_from_options(**options):
    """Get config file fragment reflecting command-line options."""
    data = []
    if options.get("daemonize",False):
        data.append("[supervisord]\nnodaemon=false\n")
    else:
        data.append("[supervisord]\nnodaemon=true\n")
    for progame, in options.get("launch",None) or []:
        data.append("[program:%s]\nautostart=true\n" % (progname,))
    for progname in options.get("exclude",None) or []:
        data.append("[program:%s]\nautostart=false\n" % (progname,))
    return "".join(data)


def set_if_missing(cfg,section,option,value):
    """If the given option is missing, set to the given value."""
    try:
        cfg.get(section,option)
    except NoSectionError:
        cfg.add_section(section)
        cfg.set(section,option,value)
    except NoOptionError:
        cfg.set(section,option,value)


#  These are the default configuration options provided by djsupervisor.
#  We provide a default command "runserver" which runs the dev server.
DEFAULT_CONFIG = """

[program:runserver]
command={{ PROJECT_DIR }}/manage.py runserver --noreload

"""

