#include <Python.h>
#include <string.h>
#include "search.h"

static int ensure_python(void) {
    if (!Py_IsInitialized()) {
        Py_Initialize();
        if (!Py_IsInitialized()) {
            return -1;
        }
    }
    return 0;
}

int cc_document_search(const char *db_path, const char *term, char *outbuf, int bufsize) {
    if (ensure_python() != 0) {
        return -1;
    }
    PyGILState_STATE gstate = PyGILState_Ensure();

    PyObject *mod_index = PyImport_ImportModule("core.corpus_index");
    if (!mod_index) {
        PyGILState_Release(gstate);
        return -1;
    }
    PyObject *cls = PyObject_GetAttrString(mod_index, "CorpusIndex");
    Py_DECREF(mod_index);
    if (!cls) {
        PyGILState_Release(gstate);
        return -1;
    }
    PyObject *args = Py_BuildValue("(s)", db_path);
    PyObject *index_obj = PyObject_CallObject(cls, args);
    Py_DECREF(args);
    Py_DECREF(cls);
    if (!index_obj) {
        PyGILState_Release(gstate);
        return -1;
    }

    PyObject *mod_search = PyImport_ImportModule("core.doc_search");
    if (!mod_search) {
        Py_DECREF(index_obj);
        PyGILState_Release(gstate);
        return -1;
    }
    PyObject *func = PyObject_GetAttrString(mod_search, "document_search_native");
    Py_DECREF(mod_search);
    if (!func) {
        Py_DECREF(index_obj);
        PyGILState_Release(gstate);
        return -1;
    }
    PyObject *result_list = PyObject_CallFunction(func, "Os", index_obj, term);
    Py_DECREF(func);
    Py_DECREF(index_obj);
    if (!result_list) {
        PyGILState_Release(gstate);
        return -1;
    }

    PyObject *json_mod = PyImport_ImportModule("json");
    PyObject *dumps = PyObject_GetAttrString(json_mod, "dumps");
    Py_DECREF(json_mod);
    PyObject *json_str = PyObject_CallFunctionObjArgs(dumps, result_list, NULL);
    Py_DECREF(dumps);
    Py_DECREF(result_list);
    if (!json_str) {
        PyGILState_Release(gstate);
        return -1;
    }
    const char *c = PyUnicode_AsUTF8(json_str);
    if (!c) {
        Py_DECREF(json_str);
        PyGILState_Release(gstate);
        return -1;
    }
    strncpy(outbuf, c, bufsize - 1);
    outbuf[bufsize - 1] = '\0';
    Py_DECREF(json_str);
    PyGILState_Release(gstate);
    return 0;
}
