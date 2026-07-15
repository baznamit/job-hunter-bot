import json


class JobFilter:

    def __init__(self):

        with open("config/keywords.json", "r", encoding="utf-8") as file:
            config = json.load(file)

        self.include = [word.lower() for word in config["include"]]
        self.exclude = [word.lower() for word in config["exclude"]]

    def should_include(self, title: str):

        title = title.lower()

        include_match = any(keyword in title for keyword in self.include)

        if not include_match:
            return False

        exclude_match = any(keyword in title for keyword in self.exclude)

        return not exclude_match