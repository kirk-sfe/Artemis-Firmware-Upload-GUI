"""
This is a simple firmware upload GUI designed for the Artemis platform.
Very handy for updating devices in the field without the need for compiling
and uploading through Arduino.

This is the "integrated" version which includes code from both ambiq_bin2board.py and artemis_svl.py

If you are building with a new version of artemis_svl.bin, remember to update BOOTLOADER_VERSION below.

Based on gist by Stefan Lehmann: https://gist.github.com/stlehmann/bea49796ad47b1e7f658ddde9620dff1

MIT license

Pyinstaller:
Windows:
pyinstaller --onefile --noconsole --distpath=. --icon=artemis_firmware_uploader_gui.ico --add-data="artemis_svl.bin;." --add-data="Artemis-Logo-Rounded.png;." artemis_firmware_uploader_gui.py
Linux:
pyinstaller --onefile --noconsole --distpath=. --icon=artemis_firmware_uploader_gui.ico --add-data="artemis_svl.bin:." --add-data="Artemis-Logo-Rounded.png:." artemis_firmware_uploader_gui.py

Pyinstaller needs:
artemis_firmware_uploader_gui.py (this file!)
artemis_firmware_uploader_gui.ico (icon file for the .exe)
Artemis-Logo-Rounded.png (icon for the GUI widget)
artemis_svl.bin (the bootloader binary)

"""

# Immediately upon reset the Artemis module will search for the timing character
#   to auto-detect the baud rate. If a valid baud rate is found the Artemis will
#   respond with the bootloader version packet
# If the computer receives a well-formatted version number packet at the desired
#   baud rate it will send a command to begin bootloading. The Artemis shall then
#   respond with the a command asking for the next frame.
# The host will then send a frame packet. If the CRC is OK the Artemis will write
#   that to memory and request the next frame. If the CRC fails the Artemis will
#   discard that data and send a request to re-send the previous frame.
# This cycle repeats until the Artemis receives a done command in place of the
#   requested frame data command.
# The initial baud rate determination must occur within some small timeout. Once
#   baud rate detection has completed all additional communication will have a
#   universal timeout value. Once the Artemis has begun requesting data it may no
#   no longer exit the bootloader. If the host detects a timeout at any point it
#   will stop bootloading.

# Notes about PySerial timeout:
# The timeout operates on whole functions - that is to say that a call to
#   ser.read(10) will return after ser.timeout, just as will ser.read(1) (assuming
#   that the necessary bytes were not found)
# If there are no incoming bytes (on the line or in the buffer) then two calls to
#   ser.read(n) will time out after 2*ser.timeout
# Incoming UART data is buffered behind the scenes, probably by the OS.

# Information about the firmware updater (taken from ambiq_bin2board.py):
#   This script performs the three main tasks:
#       1. Convert 'application.bin' to an OTA update blob
#       2. Convert the OTA blob into a wired update blob
#       3. Push the wired update blob into the Artemis module

from typing import Iterator, Tuple
from PyQt5.QtCore import QSettings, QProcess, QTimer, pyqtSignal, pyqtSlot, QObject, Qt
from PyQt5.QtWidgets import QWidget, QLabel, QComboBox, QGridLayout, \
    QPushButton, QApplication, QLineEdit, QFileDialog, QPlainTextEdit, \
    QAction, QActionGroup, QMenu, QMenuBar, QMainWindow
from PyQt5.QtGui import QCloseEvent, QTextCursor, QIcon, QFont, QPixmap
from PyQt5.QtSerialPort import QSerialPortInfo
import sys
import time
import math
import os
import serial
from Crypto.Cipher import AES # pip install pycryptodome
import array
import hashlib
import hmac
import binascii
import os.path


# What version is this app (need something)
_APP_VERSION = "v3.0.0"
_APP_NAME = "Artemis Firmware Uploader"

# sub folder for our resource files
_RESOURCE_DIRECTORY = "resource"
#---------------------------------------------------------------------------------------
# resource_path()
#
# Get the runtime path of app resources. This changes depending on how the app is
# run -> locally, or via pyInstaller
#
#https://stackoverflow.com/a/50914550

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """

    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, _RESOURCE_DIRECTORY, relative_path)

#--------------------------------------------------------------------------------------

# determine the current GUI style (TODO: Is there another way to do this?)
import darkdetect
import platform

# import action things
from .au_action import AxAction, AxJob

from .au_act_artasb  import AUxArtemisBurnBootloader
from .au_act_artfrmw import AUxArtemisUploadFirware


from .au_worker import AUxWorker

#----------------------------------------------------------------
# hack to know when a combobox menu is being shown. Helpful if contents
# of list are dynamic -- like serial ports.
class AUxComboBox(QComboBox):

    popupAboutToBeShown = pyqtSignal()

    def showPopup(self):
        self.popupAboutToBeShown.emit()
        super().showPopup()

#----------------------------------------------------------------
# ux_is_darkmode()
#
# Helpful function used during setup to determine if the Ux is in 
# dark mode
_is_darkmode = None
def ux_is_darkmode() -> bool:
    global _is_darkmode

    if _is_darkmode != None:
        return _is_darkmode

    osName = platform.system()

    if osName == "Darwin":
        _is_darkmode = darkdetect.isDark()

    elif osName == "Windows":
        # it appears that the Qt interface on Windows doesn't apply DarkMode
        # So, just keep it light
        _is_darkmode = False
    elif osName == "Linux":
        # Need to check this on Linux at some pont
        _is_darkmod = False

    else: 
        _is_darkmode = False 

    return _is_darkmode

#--------------------------------------------------------------------------------------

BOOTLOADER_VERSION = 5 # << Change this to match the version of artemis_svl.bin

# Setting constants
SETTING_PORT_NAME = 'port_name'
SETTING_FILE_LOCATION = 'message'
SETTING_BAUD_RATE = '115200' # Default to 115200 for upload
SETTING_ARTEMIS = 'True' # Default to Artemis-based boards

def gen_serial_ports() -> Iterator[Tuple[str, str, str]]:
    """Return all available serial ports."""
    ports = QSerialPortInfo.availablePorts()
    return ((p.description(), p.portName(), p.systemLocation()) for p in ports)

# noinspection PyArgumentList

#---------------------------------------------------------------------------------------
class MainWindow(QMainWindow):
    """Main Window"""

    sig_message     = pyqtSignal(str)
    sig_finished    = pyqtSignal(int)

    def __init__(self, parent: QMainWindow = None) -> None:
        super().__init__(parent)

        self.installed_bootloader = -1 # Use this to record the bootloader version

        # ///// START of code taken from ambiq_bin2board.py

        #
        self.appFile = 'artemis_svl.bin'    # --bin Bootloader binary file
        
        self.load_address_blob = 0xC000     # --load-address-wired  dest=loadaddress_blob   default=0x60000
        self.load_address_image = 0x20000   # --load-address-blob   dest=loadaddress_image  default=AM_SECBOOT_DEFAULT_NONSECURE_MAIN=0xC000
        self.magic_num = 0xCB       # --magic-num   Magic Num (AM_IMAGE_MAGIC_NONSECURE)
        

        # File location line edit
        msg_label = QLabel(self.tr('Firmware File:'))
        self.fileLocation_lineedit = QLineEdit()
        msg_label.setBuddy(self.fileLocation_lineedit)
        self.fileLocation_lineedit.setEnabled(False)
        self.fileLocation_lineedit.returnPressed.connect(
            self.on_browse_btn_pressed)

        # Browse for new file button
        browse_btn = QPushButton(self.tr('Browse'))
        browse_btn.setEnabled(True)
        browse_btn.pressed.connect(self.on_browse_btn_pressed)

        # Port Combobox
        port_label = QLabel(self.tr('COM Port:'))
        self.port_combobox = AUxComboBox()
        port_label.setBuddy(self.port_combobox)
        self.update_com_ports()
        self.port_combobox.popupAboutToBeShown.connect(self.on_port_combobox)


        # Baudrate Combobox
        baud_label = QLabel(self.tr('Baud Rate:'))
        self.baud_combobox = QComboBox()
        baud_label.setBuddy(self.baud_combobox)
        self.update_baud_rates()

        # Upload Button
        myFont=QFont()
        myFont.setBold(True)
        self.upload_btn = QPushButton(self.tr('  Upload Firmware  '))
        self.upload_btn.setFont(myFont)
        self.upload_btn.pressed.connect(self.on_upload_btn_pressed)

        # Upload Button
        self.updateBootloader_btn = QPushButton(self.tr(' Update Bootloader '))
        self.updateBootloader_btn.pressed.connect(self.on_update_bootloader_btn_pressed)

        # Messages Bar
        messages_label = QLabel(self.tr('Status / Warnings:'))

        # Messages/Console Window
        self.messages = QPlainTextEdit()
        color =  "C0C0C0" if ux_is_darkmode() else "424242"
        self.messages.setStyleSheet("QPlainTextEdit { color: #" + color + ";}")

        # Attempting to reduce window size
        #self.messages.setMinimumSize(1, 2)
        #self.messages.resize(1, 2)

        # Menu Bar
        menubar = self.menuBar()
        boardMenu = menubar.addMenu('Board Type')
        
        boardGroup = QActionGroup(self)

        self.artemis = QAction('Artemis', self, checkable=True)
        self.artemis.setStatusTip('Artemis-based boards including the OLA and AGT')
        self.artemis.setChecked(True) # Default to artemis
        a = boardGroup.addAction(self.artemis)
        boardMenu.addAction(a)
        
        self.apollo3 = QAction('Apollo3', self, checkable=True)
        self.apollo3.setStatusTip('Apollo3 Blue development boards including the SparkFun Edge')
        a = boardGroup.addAction(self.apollo3)
        boardMenu.addAction(a)

        # Add an artemis logo to the user interface
        logo = QLabel(self)
        icon = "artemis-icon.png" if ux_is_darkmode() else "artemis-icon-blk.png"
        pixmap = QPixmap(resource_path(icon))
        logo.setPixmap(pixmap)

        # Arrange Layout
        layout = QGridLayout()
        
        layout.addWidget(msg_label, 1, 0)
        layout.addWidget(self.fileLocation_lineedit, 1, 1)
        layout.addWidget(browse_btn, 1, 2)

        layout.addWidget(port_label, 2, 0)
        layout.addWidget(self.port_combobox, 2, 1)

        layout.addWidget(logo, 2,2, 2,3, alignment=Qt.AlignCenter)

        layout.addWidget(baud_label, 3, 0)
        layout.addWidget(self.baud_combobox, 3, 1)

        layout.addWidget(messages_label, 4, 0)
        layout.addWidget(self.messages, 5, 0, 5, 3)

        layout.addWidget(self.upload_btn, 15, 2)
        layout.addWidget(self.updateBootloader_btn, 15, 0)

        widget = QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)


        #self._clean_settings() # This will delete all existing settings! Use with caution!
        
        self._load_settings()

        # Make the text edit window read-only
        self.messages.setReadOnly(True)
        self.messages.clear()  # Clear the message window

        self.setWindowTitle( _APP_NAME + " - " + _APP_VERSION)

        # Initial Status Bar
        self.statusBar().showMessage(_APP_NAME + " - " + _APP_VERSION, 10000)


        # setup our background worker thread ...

        # connect the signals from the background processor to callback
        # methods/slots. This makes it thread safe
        self.sig_message.connect(self.log_message)
        self.sig_finished.connect(self.on_finished)

        # Create our background worker object, which also will do wonk in it's 
        # own thread. 
        self._worker = AUxWorker(self.on_worker_callback)

        # add the actions/commands for this app to the background processing thread. 
        # These actions are passed jobs to execute. 
        self._worker.add_action(AUxArtemisUploadFirware(), AUxArtemisBurnBootloader())


    #--------------------------------------------------------------
    # callback function for the background worker.
    #
    # It is assumed that this method is called by the background thread
    # so signals and used to relay the call to the GUI running on the
    # main thread

    def on_worker_callback(self, type, arg):

        if type == AUxWorker.TYPE_MESSAGE:
            self.sig_message.emit(arg)
        elif type == AUxWorker.TYPE_FINISHED:
            self.sig_finished.emit(arg)

    #--------------------------------------------------------------
    @pyqtSlot(str)
    def log_message(self, msg: str) -> None:
        """Add msg to the messages window, ensuring that it is visible"""

        # The passed in text is inserted *raw* at the end of the console
        # text area. The insert method doesn't add any newlines. Most of the
        # text being recieved originates in a print() call, which adds newlines.

        self.messages.moveCursor(QTextCursor.End)

        ## Backspace ("\b")?? 
        tmp = msg
        while len(tmp) > 2 and tmp.startswith('\b'):

            # remove the "\b" from the input string, and delete the 
            # previous character from the cursor in the text console
            tmp = tmp[1:]
            self.messages.textCursor().deletePreviousChar()
            self.messages.moveCursor(QTextCursor.End)

        # insert the new text at the end of the console
        self.messages.insertPlainText(tmp)

        # make sure cursor is at end of text and it's visible
        self.messages.moveCursor(QTextCursor.End)
        self.messages.ensureCursorVisible()

        self.repaint() # Update/refresh the message window

    #--------------------------------------------------------------
    # on_finished()
    #
    #  Slot for sending the "on finished" signal from the background thread
    # 
    #  Called when the backgroudn job is finished and includes a status value
    @pyqtSlot(int)
    def on_finished(self, status) -> None:

        # re-enable the UX 
        self.disable_interface(False)

        # update the status message
        msg = "successfully" if status == 0 else "with an error"
        self.statusBar().showMessage("The upload process finished " + msg, 2000)        

    #--------------------------------------------------------------
    # on_port_combobox()
    #
    # Called when the combobox pop-up menu is about to be shown
    #
    # Use this event to dynamically update the displayed ports
    #
    @pyqtSlot()
    def on_port_combobox(self):
        self.statusBar().showMessage("Updating ports...", 500)
        self.update_com_ports()


    #---------------------------------------------------------------

    def _load_settings(self) -> None:
        """Load settings on startup."""
        settings = QSettings()

        port_name = settings.value(SETTING_PORT_NAME)
        if port_name is not None:
            index = self.port_combobox.findData(port_name)
            if index > -1:
                self.port_combobox.setCurrentIndex(index)

        lastFile = settings.value(SETTING_FILE_LOCATION)
        if lastFile is not None:
            self.fileLocation_lineedit.setText(lastFile)

        baud = settings.value(SETTING_BAUD_RATE)
        if baud is not None:
            index = self.baud_combobox.findData(baud)
            if index > -1:
                self.baud_combobox.setCurrentIndex(index)

        checked = settings.value(SETTING_ARTEMIS)
        if checked is not None:
            if (checked == 'True'):
                self.artemis.setChecked(True)
                self.apollo3.setChecked(False)
            else:
                self.artemis.setChecked(False)
                self.apollo3.setChecked(True)

    #--------------------------------------------------------------
    def _save_settings(self) -> None:
        """Save settings on shutdown."""
        settings = QSettings()
        settings.setValue(SETTING_PORT_NAME, self.port)
        settings.setValue(SETTING_FILE_LOCATION, self.fileLocation_lineedit.text())
        settings.setValue(SETTING_BAUD_RATE, self.baudRate)
        if (self.artemis.isChecked()): # Convert isChecked to str
            checkedStr = 'True'
        else:
            checkedStr = 'False'
        settings.setValue(SETTING_ARTEMIS, checkedStr)

    #--------------------------------------------------------------
    def _clean_settings(self) -> None:
        """Clean (remove) all existing settings."""
        settings = QSettings()
        settings.clear()

    #--------------------------------------------------------------
    def show_error_message(self, msg: str) -> None:
        """Show a Message Box with the error message."""
        QMessageBox.critical(self, QApplication.applicationName(), str(msg))

    #--------------------------------------------------------------
    def update_com_ports(self) -> None:
        """Update COM Port list in GUI."""
        previousPort = self.port # Record the previous port before we clear the combobox
        
        self.port_combobox.clear()

        index = 0
        indexOfCH340 = -1
        indexOfPrevious = -1
        for desc, name, sys in gen_serial_ports():

            longname = desc + " (" + name + ")"
            self.port_combobox.addItem(longname, sys)
            if("CH340" in longname):
                # Select the first available CH340
                # This is likely to only work on Windows. Linux port names are different.
                if (indexOfCH340 == -1):
                    indexOfCH340 = index
                    # it could be too early to call
                    #self.log_message("CH340 found at index " + str(indexOfCH340))
                    # as the GUI might not exist yet
            if(sys == previousPort): # Previous port still exists so record it
                indexOfPrevious = index
            index = index + 1

        if indexOfPrevious > -1: # Restore the previous port if it still exists
            self.port_combobox.setCurrentIndex(indexOfPrevious)
        if indexOfCH340 > -1: # If we found a CH340, let that take priority
            self.port_combobox.setCurrentIndex(indexOfCH340)

    #--------------------------------------------------------------
    # Is a port still valid?

    def verify_port(self, port) -> bool:

        # Valid inputs - Check the port
        for desc, name, sys in gen_serial_ports():
            if sys == port:
                return True

        return False
    #--------------------------------------------------------------
    def update_baud_rates(self) -> None:
        """Update baud rate list in GUI."""
        # Lowest speed first so code defaults to that
        # if settings.value(SETTING_BAUD_RATE) is None
        self.baud_combobox.clear()
        self.baud_combobox.addItem("115200", 115200)
        self.baud_combobox.addItem("460800", 460800)
        self.baud_combobox.addItem("921600", 921600)

    #--------------------------------------------------------------
    @property
    def port(self) -> str:
        """Return the current serial port."""
        return self.port_combobox.currentData()

    #--------------------------------------------------------------
    @property
    def baudRate(self) -> str:
        """Return the current baud rate."""
        return self.baud_combobox.currentData()

    #--------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle Close event of the Widget."""
        self._save_settings()

        # shutdown the background worker/stop it so the app exits correctly
        self._worker.shutdown()

        event.accept()

    #--------------------------------------------------------------
    # disable_interface()
    #
    # Enable/Disable portions of the ux - often used when a job is running
    #
    def disable_interface(self, bDisable=False):

        self.upload_btn.setDisabled(bDisable)
        self.updateBootloader_btn.setDisabled(bDisable)

    #--------------------------------------------------------------
    # on_uplaod_btn_pressed()
    #

    def on_upload_btn_pressed(self) -> None:
        
        # Valid inputs - Check the port
        if not self.verify_port(self.port):
            self.log_message("Port No Longer Available")
            return

        # Does the upload file exist?
        fmwFile = self.fileLocation_lineedit.text()
        if not os.path.exists(fmwFile):
            self.log_message("The firmware file was not found: " + fmwFile)
            return
        
        # Create a job and add it to the job queue. The worker thread will pick this up and
        # process the job. Can set job values using dictionary syntax, or attribut assignments
        # 
        # Note - the job is defined with the ID of the target action
        theJob = AxJob(AUxArtemisUploadFirware.ACTION_ID, {"port":self.port, "baud":self.baudRate, "file":fmwFile})

        # Send the job to the worker to process
        self._worker.add_job(theJob)

        self.disable_interface(True)

    #--------------------------------------------------------------
    def on_update_bootloader_btn_pressed(self) -> None:


        # Valid inputs - Check the port
        if not self.verify_port(self.port):
            self.log_message("Port No Longer Available")
            return

        # Does the bootloader file exist?
        blFile = resource_path(self.appFile)
        if not os.path.exists(blFile):
            self.log_message("The bootloader file was not found: " + blFile)
            return

        # Make up a job and add it to the job queue. The worker thread will pick this up and
        # process the job. Can set job values using dictionary syntax, or attribut assignments
        theJob = AxJob(AUxArtemisBurnBootloader.ACTION_ID,  {"port":self.port, "baud":self.baudRate, "file":blFile})

        # Send the job to the worker to process
        self._worker.add_job(theJob)

        self.disable_interface(True)

    #--------------------------------------------------------------
    def on_browse_btn_pressed(self) -> None:
        """Open dialog to select bin file."""

        self.statusBar().showMessage("Select firmware file for upload...", 4000)
        options = QFileDialog.Options()
        fileName, _ = QFileDialog.getOpenFileName(
            None,
            "Select Firmware to Upload",
            "",
            "Firmware Files (*.bin);;All Files (*)",
            options=options)
        if fileName:
            self.fileLocation_lineedit.setText(fileName)


def startArtemisUploader():
    import sys
    app = QApplication([])
    app.setOrganizationName('SparkFun Electronics')
    app.setApplicationName(_APP_NAME + ' - ' + _APP_VERSION)
    app.setWindowIcon(QIcon(resource_path("artemis-logo-rounded.png")))
    app.setApplicationVersion(_APP_VERSION)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    startArtemisUploader()