#include <Python.h>
#include <libgen.h>
#include <stdio.h>
#include <stdlib.h>
#include <mach-o/dyld.h>
#include <string.h>
#include <unistd.h>
#include <sys/param.h>

static void handle_status(PyStatus status, PyConfig *config) {
    if (PyStatus_Exception(status)) {
        if (config != NULL) {
            PyConfig_Clear(config);
        }
        Py_ExitStatusException(status);
    }
}

int main(int argc, char *argv[]) {
    PyConfig config;
    PyStatus status;
    int exit_code;
    char python_home_link[PATH_MAX];
    char python_home[PATH_MAX];
    char python_path[PATH_MAX];
    char program_name[PATH_MAX];

    // Determine app bundle paths relative to executable
    char executable_path[PATH_MAX];
    uint32_t exec_size = sizeof(executable_path);

    if (_NSGetExecutablePath(executable_path, &exec_size) != 0) {
        fprintf(stderr, "python3_embed: Failed to get executable path\n");
        return 1;
    }

    // Get the directory containing the executable
    char *app_dir = dirname(executable_path);
    char *contents_dir = dirname(app_dir);

    if (!app_dir || !contents_dir) {
        fprintf(stderr, "python3_embed: Failed to resolve app directory structure\n");
        return 1;
    }

    // Construct Python framework path using the Current symlink and resolve it
    snprintf(python_home_link, sizeof(python_home_link), "%s/Frameworks/Python.framework/Versions/Current", contents_dir);
    if (!realpath(python_home_link, python_home)) {
        fprintf(stderr, "python3_embed: Unable to resolve Python home at %s\n", python_home_link);
        return 1;
    }

    const char *version_component = strrchr(python_home, '/');
    const char *python_version = (version_component && *(version_component + 1) != '\0') ? version_component + 1 : "3.10";
    snprintf(program_name, sizeof(program_name), "%s/bin/python3", python_home);

    // Verify python_site exists
    char python_site_path[PATH_MAX];
    snprintf(python_site_path, sizeof(python_site_path), "%s/Resources/python_site", contents_dir);
    if (access(python_site_path, R_OK) != 0) {
        fprintf(stderr, "python3_embed: python_site not found at %s\n", python_site_path);
        return 1;
    }

    // Set up Python path to include bundled python_site
    snprintf(python_path, sizeof(python_path), "%s/Resources/python_site:%s/lib/python%s:%s/lib/python%s/lib-dynload",
             contents_dir, python_home, python_version, python_home, python_version);

    PyConfig_InitPythonConfig(&config);
    config.use_environment = 0;
    config.user_site_directory = 0;
    config.write_bytecode = 0;

    // Configure to use bundled Python framework only
    status = PyConfig_SetBytesString(&config, &config.program_name, program_name);
    handle_status(status, &config);

    status = PyConfig_SetBytesString(&config, &config.home, python_home);
    handle_status(status, &config);

    // Set Python path to use bundled modules only
    status = PyConfig_SetBytesString(&config, &config.pythonpath_env, python_path);
    handle_status(status, &config);

    // Ensure we don't use system Python
    config.isolated = 1;
    config.use_environment = 0;
    config.configure_c_stdio = 0;
    config.buffered_stdio = 0;

    status = PyConfig_SetBytesArgv(&config, argc, argv);
    handle_status(status, &config);

    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    handle_status(status, NULL);

    exit_code = Py_RunMain();
    return exit_code;
}
