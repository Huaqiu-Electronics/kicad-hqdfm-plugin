class RC_ITEM:
    def __init__(self):
        self.m_errorCode = 0
        self.m_errorMessage = ""
        self.m_errorTitle = ""
        self.m_settingsKey = ""
        self.m_parent = None
        self.m_ids = []

    def SetErrorMessage(self, message):
        self.m_errorMessage = message

    def SetItems(self, ids):
        self.m_ids = ids

    def AddItem(self, item):
        self.m_ids.append(item)

    def SetParent(self, parent):
        self.m_parent = parent

    def GetMainItemID(self):
        return self.m_ids[0] if self.m_ids else None

    def GetAuxItemID(self):
        return self.m_ids[1] if len(self.m_ids) > 1 else None

    def GetAuxItem2ID(self):
        return self.m_ids[2] if len(self.m_ids) > 2 else None

    def GetAuxItem3ID(self):
        return self.m_ids[3] if len(self.m_ids) > 3 else None

    def GetIDs(self):
        return self.m_ids

    def ShowReport(self, aUnitsProvider, aSeverity, aItemMap):
        # Translate this object into a text string suitable for saving to disk in a report
        pass

    def GetJsonViolation(self, aViolation, aUnitsProvider, aSeverity, aItemMap):
        # Translate this object into an RC_JSON::VIOLATION object
        pass

    def GetErrorCode(self):
        return self.m_errorCode

    def SetErrorCode(self, code):
        self.m_errorCode = code

    def GetErrorMessage(self):
        return self.m_errorMessage

    def GetErrorText(self):
        return self.m_errorTitle

    def GetSettingsKey(self):
        return self.m_settingsKey

    def GetViolatingRuleDesc(self):
        return ""
