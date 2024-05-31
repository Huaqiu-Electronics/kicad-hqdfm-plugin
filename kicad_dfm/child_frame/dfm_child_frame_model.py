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
# 定义列的最大数量
MAX_COLS = 2


class DfmChildFrameModel(dv.DataViewIndexListModel):
    def __init__(self, data):
        dv.DataViewIndexListModel.__init__(self, len(data))
        self.data = data

        # self.log = log

    # This method is called to provide the data object for a
    # particular row,col
    def GetValueByRow(self, row, col):
        # 检查行索引是否在有效范围内
        if col < 0 or col >= MAX_COLS:
            return None
        try:
            # 使用循环来获取数据，而不是多个 elif 语句
            return self.data[row][col]

        except IndexError as e:
            # 如果 row 索引超出了范围，捕获错误
            print(f"Error: Row index {row} is out of range. {e}")
            return None
        except Exception as e:
            # 捕获其他可能的错误
            print(f"An unexpected error occurred: {e}")
            return None

    def GetAttrByRow(self, row, col, attr):
        ##self.log.write('GetAttrByRow: (%d, %d)' % (row, col))
        if col == 0 and self.data[row][1] == "red":
            attr.SetColour("red")
            return True
        elif col == 0 and self.data[row][1] == "black":
            attr.SetColour("black")
            return True
        elif col == 0 and self.data[row][1] == "gold":
            attr.SetColour(wx.Colour(255, 165, 0))
            return True

    # This method is called when the user edits a data item in the view.
    def SetValueByRow(self, value, row, col):
        # 根据列的索引更新数据
        if 0 <= col < len(self.data[row]):
            self.data[row][col] = value
            self.RowChanged(row)
            return True
        return False

    # Report how many columns this model provides data for.
    def GetColumnCount(self):
        return MAX_COLS

    # Specify the data type for a column
    def GetColumnType(self, col):
        return "string"  # 所有列的数据类型都是字符串

    # Report the number of rows in the model
    def GetCount(self):
        # self.log.write('GetCount')
        return len(self.data)

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
            return 0

    def DeleteRows(self, rows):
        # 删除行的实现
        rows = list(rows)
        # use reverse order so the indexes don't change as we remove items
        rows.sort(reverse=True)

        for row in rows:
            # remove it from our data structure
            del self.data[row]
            # notify the view(s) using this model that it has been removed
            self.RowDeleted(row)

    def DeleteAll(self):
        # 删除行的实现
        total_rows = self.GetCount()
        self.data = []
        for row in range(total_rows - 1, -1, -1):
            self.RowDeleted(row)

    def AddRow(self, value):
        # update data structure
        self.data.append(value)
        # notify views
        self.RowAppended()

    def AddRows(self, values):
        for row_index, new_value in enumerate(values):
            # 添加新行到数据结构
            self.data.append(new_value)
            # 通知模型新行已被添加
            self.RowAppended()

    def Update(self, datas):
        self.DeleteAll()
        # self.data = []
        # for data in datas:
        # self.data = datas
        for new_value in datas:
            # 添加新行到数据结构
            self.data.append(new_value)
            # 通知模型新行已被添加
            self.RowAppended()
