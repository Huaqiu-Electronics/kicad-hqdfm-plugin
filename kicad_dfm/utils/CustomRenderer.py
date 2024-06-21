import sys
import wx
import wx.dataview as dv
import os

# import os; print('PID:'+str(os.getpid())); raw_input("Press enter...")

# ----------------------------------------------------------------------


class MyCustomRenderer(dv.DataViewCustomRenderer):
    def __init__(self, log, *args, **kw):
        dv.DataViewCustomRenderer.__init__(self, *args, **kw)
        self.log = log
        self.value = None

    def SetValue(self, value):
        # self.log.write('MyCustomRenderer.SetValue: %s\n' % value)
        self.value = value
        return True

    def GetValue(self):
        # self.log.write('MyCustomRenderer.GetValue\n')
        return self.value

    def GetSize(self):
        # Return the size needed to display the value.  The renderer
        # has a helper function we can use for measuring text that is
        # aware of any custom attributes that may have been set for
        # this item.
        value = self.value if self.value else ""
        size = self.GetTextExtent(value)
        # "Windows"
        if os.name == "nt":
            size.height = 35
        # "Linux"
        elif os.name == "posix":
            size.height = 32
        else:
            size.height = 35
        return size

    def Render(self, rect, dc, state):
        if state != 0:
            self.log.write("Render: %s, %d\n" % (rect, state))
            dc.SetTextForeground(wx.Colour("black"))

        # And then finish up with this helper function that draws the
        # text for us, dealing with alignment, font and color
        # attributes, etc
        value = self.value if self.value else ""
        self.RenderText(
            value,
            0,  # x-offset, to compensate for the rounded rectangles
            rect,
            dc,
            state=0,  # wxDataViewCellRenderState flags
        )
        return True

    # The HasEditorCtrl, CreateEditorCtrl and GetValueFromEditorCtrl
    # methods need to be implemented if this renderer is going to
    # support in-place editing of the cell value, otherwise they can
    # be omitted.

    def HasEditorCtrl(self):
        self.log.write("HasEditorCtrl")
        return True

    def CreateEditorCtrl(self, parent, labelRect, value):
        self.log.write("CreateEditorCtrl: %s" % labelRect)
        ctrl = wx.TextCtrl(
            parent, value=value, pos=labelRect.Position, size=labelRect.Size
        )

        # select the text and put the caret at the end
        ctrl.SetInsertionPointEnd()
        ctrl.SelectAll()

        return ctrl

    def GetValueFromEditorCtrl(self, editor):
        self.log.write("GetValueFromEditorCtrl: %s" % editor)
        value = editor.GetValue()
        return True, value

    # The LeftClick and Activate methods serve as notifications
    # letting you know that the user has either clicked or
    # double-clicked on an item.  Implementing them in your renderer
    # is optional.

    def LeftClick(self, pos, cellRect, model, item, col):
        self.log.write("LeftClick")
        return False

    def Activate(self, cellRect, model, item, col):
        self.log.write("Activate")
        return False
