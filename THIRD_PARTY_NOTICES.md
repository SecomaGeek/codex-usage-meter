# Third-party notices

The application source is MIT licensed. No Python interpreter or third-party binary
is committed to the source repository. A Windows frozen build contains components
supplied by the Python installation and PyInstaller.

- **CPython / bundled standard-library components**: see `licenses/Python-LICENSE.txt` in the distribution. The matching official `licenses/CPython-3.13.5-license.html` also contains notices for bundled OpenSSL, libffi, zlib and other components.
- **Tcl/Tk**: see `licenses/Tcl-license.terms` and `licenses/Tk-license.terms`.
- **PyInstaller 6.16.0**: GPL with its bootloader exception; applicable runtime files also have Apache-2.0 licensing. The full installed distribution metadata is copied to `licenses/pyinstaller/`.
- **Microsoft Visual C++ runtime**: provided by the official Python Windows distribution; the interpreter license notice and the installed runtime's redistribution terms apply.

Builds copy notices from the exact build environment rather than substituting a
license from a different binary version. If a required notice is missing, the
build stops so that it can be supplied before redistribution.

References: [Python license](https://docs.python.org/3/license.html),
[PyInstaller license](https://pyinstaller.org/en/v6.16.0/license.html).
