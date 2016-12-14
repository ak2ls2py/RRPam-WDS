from rrpam_wds.gui import set_pyqt_api  # isort:skip # NOQA
import sys, os
import time
import unittest

import mock
import numpy as np
from guiqwt.curve import CurveItem
from guiqwt.shapes import EllipseShape
from PyQt5.QtWidgets import QApplication

from rrpam_wds.gui.dialogs import MainWindow, LogDialog
from rrpam_wds  import logger

class TestLoggers(unittest.TestCase):
    start = 0
    stop = 0

    def setUp(self):
        global start
        self.app = QApplication(sys.argv)
        start = time.time()

    def tearDown(self):
        global stop
        stop = time.time()
        print("\ncalculation took %0.2f seconds." % (stop - start))
        self.aw = None

    def runTest(self):
        """ otherwise python 2.7 returns an error
        ValueError: no such test method in <class 'myapp.tests.SessionTestCase'>: runTest"""

    def test_creating_main_window_will_write_log_messages(self):
        with open(os.path.join(os.path.dirname(logger.__file__),"log","info.log"),'r') as f:
            self.aw = MainWindow()
            log=self.aw.logwindow.toPlainText()
            self.assertEqual(log,self.aw.LOGSTARTMESSAGE)
            self.aw.show_logwindow()
            
    def test_calling_show_log_in_main_window_will_show_log_dialog(self):
        self.aw = MainWindow()
        self.assertFalse([x for x in self.aw.mdi.subWindowList() if isinstance(x.widget(),LogDialog)])
        self.aw.show_logwindow()
        li=[x for x in self.aw.mdi.subWindowList() if  isinstance(x.widget(),LogDialog)]
        self.assertTrue(li)
        self.assertEqual(li[0].widget().logwindow,self.aw.logwindow)


def drive(test=True):  # pragma: no cover
    if(test):
        unittest.main(verbosity=2)
    else:
        ot = TestLoggers()
        ot.setUp()
        ot.test_calling_show_log_in_main_window_will_show_log_dialog()
        ot.aw.show()
        sys.exit(ot.app.exec_())

if __name__ == '__main__':  # pragma: no cover
    drive(test=False)
