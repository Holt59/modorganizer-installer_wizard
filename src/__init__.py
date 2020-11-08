# -*- encoding: utf-8 -*-

"""
This file is the entry point of the module and must contain a createPlugin()
or createPlugins() function.
"""

import os
import site

site.addsitedir(os.path.join(os.path.dirname(__file__), "lib"))

from .installer import WizardInstaller  # noqa: E402


def createPlugin() -> WizardInstaller:
    return WizardInstaller()
