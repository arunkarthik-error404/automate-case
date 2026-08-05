"""Stub service-account credentials — tests never talk to Google."""


class Credentials:
    @staticmethod
    def from_service_account_info(info, scopes=None):
        return Credentials()

    @staticmethod
    def from_service_account_file(path, scopes=None):
        return Credentials()
