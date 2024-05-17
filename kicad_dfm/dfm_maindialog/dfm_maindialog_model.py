import sys
import wx
import wx.dataview as dv

# ----------------------------------------------------------------------

# This model class provides the data to the view when it is asked for.
# Since it is a list-only model (no hierarchical data) then it is able
# to be referenced by row rather than by item object, so in this way
# it is easier to comprehend and use than other model types.  In this
# example we also provide a Compare function to assist with sorting of
# items in our model.  Notice that the data items in the data model
# object don't ever change position due to a sort or column
# reordering.  The view manages all of that and maps view rows and
# columns to the model's rows and columns as needed.
#
# For this example our data is stored in a simple list of lists.  In
# real life you can use whatever you want or need to hold your data.


class DfmMaindialogModel(dv.DataViewIndexListModel):
    def __init__(self, data):
        dv.DataViewIndexListModel.__init__(self, len(data))
        self.data = [
            [key, value["display"], value["color"]] for key, value in data.items()
        ]

        # self.log = log

    # This method is called to provide the data object for a
    # particular row,col
    def GetValueByRow(self, row, col):
        # 根据行列获取数据，这里假设col为0时获取键，为1时获取'display'，为2时获取'color'
        if col == 0:  # 第一列显示键
            return self.data[row][0]
        elif col == 1:  # 第二列显示 value['display']
            return self.data[row][1]
        elif col == 2:  # 第三列显示 value['color']
            return self.data[row][2]
        return None  # 默认返回 None

    # This method is called when the user edits a data item in the view.
    def SetValueByRow(self, value, row, col):
        # 根据列的索引更新数据
        if 0 <= col < len(self.data[row]):
            self.data[row][col] = value
            return True
        return False

    # Report how many columns this model provides data for.
    def GetColumnCount(self):
        return 3  # 固定为3列

    # Specify the data type for a column
    def GetColumnType(self, col):
        return "string"  # 所有列的数据类型都是字符串

    # Report the number of rows in the model
    def GetCount(self):
        # self.log.write('GetCount')
        return len(self.data)

    # Called to check if non-standard attributes should be used in the
    # cell at (row, col)
    def GetAttrByRow(self, row, col, attr):
        ##self.log.write('GetAttrByRow: (%d, %d)' % (row, col))
        if col == 1 and self.data[row][2] == "red":  # 第三列有颜色值
            attr.SetColour("red")  # 设置单元格颜色
            return True
        elif col == 1 and self.data[row][2] == "black":  # 第三列有颜色值
            attr.SetColour("black")  # 设置单元格颜色
            return True
        elif col == 1 and self.data[row][2] == "gold":  # 第三列有颜色值
            attr.SetColour(wx.Colour(255, 165, 0))  # 设置单元格颜色
            return True

        # if col == 1:  # 检查数据是否包含'red_trigger'
        #     # 50%概率触发红色
        #         attr.SetColour('red')  # 将文本颜色设置为红色
        #         return True
        return False

    # This is called to assist with sorting the data in the view.  The
    # first two args are instances of the DataViewItem class, so we
    # need to convert them to row numbers with the GetRow method.
    # Then it's just a matter of fetching the right values from our
    # data set and comparing them.  The return value is -1, 0, or 1,
    # just like Python's cmp() function.
    def Compare(self, item1, item2, col, ascending):
        row1 = self.GetRow(item1)
        row2 = self.GetRow(item2)
        if col == 0:
            # 对键进行排序
            return (
                (self.data[row1][0] > self.data[row2][0])
                - (self.data[row1][0] < self.data[row2][0])
                if ascending
                else -1
                * (
                    (self.data[row1][0] > self.data[row2][0])
                    - (self.data[row1][0] < self.data[row2][0])
                )
            )
        else:
            # 对于 'display' 和 'color'，我们不进行排序
            return 0

    def DeleteRows(self, rows):
        # 删除行的实现
        for row in sorted(rows, reverse=True):
            del self.data[row]
        self.RowDeleted(row)

    def AddRow(self, value):
        # update data structure
        self.data.append(value)
        # notify views
        self.RowAppended()
