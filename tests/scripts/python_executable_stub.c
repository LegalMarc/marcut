#include <Python.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char *argv[]) {
    // Get the path to the Python framework
    char framework_path[1024];
    char *exe_path = realpath(argv[0], NULL);
    if (!exe_path) {
        fprintf(stderr, "Could not determine executable path\n");
        return 1;
    }

    // Navigate from Resources to Frameworks
    char *last_slash = strrchr(exe_path, '/');
    if (last_slash) {
        *last_slash = '\0';
        snprintf(framework_path, sizeof(framework_path),
                "%s/../Frameworks/Python.framework/Versions/3.11/Python", exe_path);
    } else {
        strcpy(framework_path, "/Users/mhm/Documents/Hobby/Marcut-2/build/MarcutApp.app/Contents/Frameworks/Python.framework/Versions/3.11/Python");
    }

    free(exe_path);

    // Set PYTHONHOME to framework directory
    char python_home[1024];
    strncpy(python_home, framework_path, sizeof(python_home));
    char *last_slash_py = strrchr(python_home, '/');
    if (last_slash_py) {
        *last_slash_py = '\0';
    }
    setenv("PYTHONHOME", python_home, 1);

    // Load the Python framework
    void *handle = dlopen(framework_path, RTLD_LAZY);
    if (!handle) {
        fprintf(stderr, "Failed to load Python framework: %s\n", dlerror());
        return 1;
    }

    // Get the main function
    int (*Py_Main)(int, char **) = dlsym(handle, "Py_Main");
    if (!Py_Main) {
        fprintf(stderr, "Failed to find Py_Main: %s\n", dlerror());
        dlclose(handle);
        return 1;
    }

    // Call Python main
    int result = Py_Main(argc, argv);

    dlclose(handle);
    return result;
}