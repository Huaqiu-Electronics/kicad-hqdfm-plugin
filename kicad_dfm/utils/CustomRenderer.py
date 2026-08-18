import sys
import wx
import wx.dataview as dv
import platform

from kicad_dfm.ui.dpi import scaled_dip

# ----------------------------------------------------------------------


class MyCustomRenderer(dv.DataViewCustomRenderer):
    def __init__(self, log, owner=None, *args, **kw):
        dv.DataViewCustomRenderer.__init__(self, *args, **kw)
        self.log = log
        self.owner = owner
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
        current_os = platform.system()

        if current_os == "Linux":
            minimum_height = 32
        else:
            minimum_height = 35
        if self.owner is not None:
            minimum_height = scaled_dip(self.owner, minimum_height)
        size.height = max(size.height, minimum_height)
        return size

    def Render(self, rect, dc, state):
        if state != 0:
            dc.SetTextForeground(wx.Colour("black"))
            # self.log.write("Render: %s, %d\n" % (rect, state))
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


class SummaryActionRenderer(dv.DataViewCustomRenderer):
    """Render and dispatch the summary action inside the scrolling view."""

    BUTTON_WIDTH_DIP = 82
    CELL_WIDTH_DIP = 90

    def __init__(self, owner, buttons, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner
        self.buttons = tuple(buttons)
        self.value = ""

    def SetValue(self, value):
        self.value = value or ""
        return True

    def GetValue(self):
        return self.value

    def GetSize(self):
        return wx.Size(
            scaled_dip(self.owner, self.CELL_WIDTH_DIP),
            scaled_dip(self.owner, 35),
        )

    def _button_rect(self, rect):
        button_rect = wx.Rect(rect)
        horizontal_margin = scaled_dip(self.owner, 4)
        button_width = min(
            scaled_dip(self.owner, self.BUTTON_WIDTH_DIP),
            max(0, button_rect.width - 2 * horizontal_margin),
        )
        button_rect.x += max(0, (button_rect.width - button_width) // 2)
        button_rect.width = button_width
        button_rect.Deflate(0, scaled_dip(self.owner, 2))
        return button_rect

    def Render(self, rect, dc, state):
        if not self.value:
            return True
        button_rect = self._button_rect(rect)
        wx.RendererNative.Get().DrawPushButton(self.owner, dc, button_rect, 0)
        # DataView changes the DC foreground to the selection text colour
        # before rendering a selected row.  A native button keeps its normal
        # face colour, so inheriting that foreground can produce white text
        # on a white button.  Use the platform button-text colour explicitly.
        dc.SetTextForeground(wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNTEXT))
        text_width, text_height = dc.GetTextExtent(self.value)
        dc.DrawText(
            self.value,
            button_rect.x + max(0, (button_rect.width - text_width) // 2),
            button_rect.y + max(0, (button_rect.height - text_height) // 2),
        )
        return True

    def LeftClick(self, pos, cellRect, model, item, col):
        return self._dispatch(model, item)

    def Activate(self, cellRect, model, item, col):
        return self._dispatch(model, item)

    def _dispatch(self, model, item):
        try:
            row = model.GetRow(item)
            button = self.buttons[row]
        except (AttributeError, IndexError, TypeError):
            return False
        if not self.value or not button.IsEnabled():
            return False
        event = wx.CommandEvent(wx.wxEVT_BUTTON, button.GetId())
        event.SetEventObject(button)
        button.GetEventHandler().ProcessEvent(event)
        return True
