import json


class JobFilter:

    def __init__(self):

        # Load keyword configuration
        with open("config/keywords.json", "r", encoding="utf-8") as file:
            keyword_config = json.load(file)

        self.include_keywords = [
            keyword.lower()
            for keyword in keyword_config["include"]
        ]

        self.exclude_keywords = [
            keyword.lower()
            for keyword in keyword_config["exclude"]
        ]

        # Load application settings
        with open("config/settings.json", "r", encoding="utf-8") as file:
            settings = json.load(file)

        self.allowed_locations = [
            location.lower()
            for location in settings["allowed_locations"]
        ]

        self.excluded_levels = [
            level.lower()
            for level in settings["excluded_levels"]
        ]

    def should_include(self, job):

        if not self._keyword_match(job.title):
            return False

        if not self._location_match(job.location):
            return False

        if not self._seniority_match(job.title):
            return False

        return True

    def _keyword_match(self, title):

        title = title.lower()

        include = any(
            keyword in title
            for keyword in self.include_keywords
        )

        if not include:
            return False

        exclude = any(
            keyword in title
            for keyword in self.exclude_keywords
        )

        return not exclude

    def _location_match(self, location):

        location = location.lower()

        return any(
            allowed_location in location
            for allowed_location in self.allowed_locations
        )

    def _seniority_match(self, title):

        title = title.lower()

        return not any(
            level in title
            for level in self.excluded_levels
        )