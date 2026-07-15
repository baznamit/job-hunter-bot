import json


class JobFilter:

    def __init__(self):

        with open("config/keywords.json") as f:
            self.keywords = json.load(f)

    def should_notify(self, title):

        title = title.lower()

        include = any(
            word.lower() in title
            for word in self.keywords["include"]
        )

        exclude = any(
            word.lower() in title
            for word in self.keywords["exclude"]
        )

        return include and not exclude