""" Main Module """

import json
import logging
import os
import gi
from threading import Timer

# pylint: disable=import-error
from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent, PreferencesEvent, PreferencesUpdateEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.item.ExtensionSmallResultItem import ExtensionSmallResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.HideWindowAction import HideWindowAction
from ulauncher.api.shared.action.OpenUrlAction import OpenUrlAction
from ulauncher.api.shared.action.OpenAction import OpenAction
from ulauncher.api.shared.action.SetUserQueryAction import SetUserQueryAction
from ulauncher.api.shared.action.RunScriptAction import RunScriptAction
from ulauncher.api.shared.action.ExtensionCustomAction import ExtensionCustomAction
from ulauncher.config import CACHE_DIR
from devdocs.devdocs_service import DevDocsService

gi.require_version('Notify', '0.7')
from gi.repository import Notify

LOGGING = logging.getLogger(__name__)


class DevdocsExtension(Extension):
    """ Main Extension Class  """

    def __init__(self):
        """ Initializes the extension """

        LOGGING.info("Initializing DevDocs extension")

        super(DevdocsExtension, self).__init__()

        # Subscribe event listeners
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.subscribe(PreferencesEvent, PreferencesEventListener())
        self.subscribe(PreferencesUpdateEvent,
                       PreferencesUpdateEventListener())
        self.subscribe(ItemEnterEvent, ItemEnterEventListener())

        # initialize DevDocs service.
        self.devdocs_svc = DevDocsService(LOGGING,
                                          os.path.join(CACHE_DIR, 'devdocs'))

    def index_docs(self):
        """ Creates a local index of all the DevDocs resources """
        self.devdocs_svc.index()

        Notify.init("UlauncherDevDocs")
        Notify.Notification.new("Ulauncher Devdocs", "Index Finished").show()

        timer = Timer(DevDocsService.get_index_cache_ttl(), self.index_docs)
        timer.daemon = True
        timer.start()

    def get_icon(self, doc_slug):
        """
        Returns the icon path for the doc
        :param str doc_slug The document slug
        """

        base_path = os.path.dirname(__file__)

        if os.path.exists(
                os.path.join(base_path, 'images', "%s.png" % doc_slug)):
            return 'images/%s.png' % doc_slug

        base_doc = doc_slug.split("~")[0]

        if os.path.exists(
                os.path.join(base_path, 'images', "%s.png" % base_doc)):
            return 'images/%s.png' % base_doc

        return 'images/icon.png'

    def open_in_devdocs(self, doc, entry=None):
        """
        Opens a documentation page in DevDocs.
        :param str doc: The documentation slug
        :param str entry: The entry slug.
        Depending of the extension configurations it might open in:
            - DevDocs website
            - Devdocs desktop (devdocs protocol)
            - HawkHeye
        """

        open_result_in = self.preferences['open_doc_in']

        doc_path = doc

        if entry:
            doc_path = doc_path + "/" + entry

        doc_url = "https://devdocs.io/%s" % doc_path

        if open_result_in == "Hawkeye":
            return RunScriptAction('hawkeye --uri="%s"' % doc_url, [])
        elif open_result_in == "DevDocs Protocol":
            return OpenAction("devdocs://%s" % doc_path)

        return OpenUrlAction(doc_url)

    def list_available_docs(self, keyword, query):
        """
        Renders a list of available Documentation, optionally filtered by the query argument
        :param str keyword: The search keyword
        :param str query: The search query.
        """
        docs = self.devdocs_svc.get_docs(query)

        if not docs:
            return RenderResultListAction([
                ExtensionResultItem(
                    icon='images/icon.png',
                    name='No documentation found matching your criteria',
                    highlightable=False,
                    on_enter=HideWindowAction())
            ])

        items = []
        for doc in docs[:10]:
            items.append(
                ExtensionResultItem(icon=self.get_icon(doc['slug']),
                                    name=doc['name'],
                                    description=doc.get('release', ""),
                                    on_enter=SetUserQueryAction(
                                        "%s %s:" % (keyword, doc['slug'])),
                                    on_alt_enter=self.open_in_devdocs(
                                        doc['slug'])))

        return RenderResultListAction(items)

    def show_entries(self, doc_slug, query):
        """
        Renders a list of available Docs
        :param str keyword: The keyword used to trigger this search
        :param str doc: The main documentation slug
        :param str query: The search term to filter the entries
        """

        entries = self.devdocs_svc.get_doc_entries(doc_slug, query)

        if not entries:
            return RenderResultListAction([
                ExtensionResultItem(
                    icon='images/icon.png',
                    name='No entries found matching your criteria',
                    highlightable=False,
                    on_enter=HideWindowAction())
            ])

        items = []
        for entry in entries[:8]:
            items.append(
                ExtensionResultItem(icon=self.get_icon(doc_slug),
                                    name=entry['name'],
                                    description=entry['type'],
                                    on_enter=self.open_in_devdocs(
                                        doc_slug, entry['path'])))

        return RenderResultListAction(items)

    def show_options_menu(self, query):
        """ Shoe some general configuration options for the extension """
        items = [
            ExtensionResultItem(
                icon='images/icon.png',
                name='Open DevDocs.io',
                description='Opens DevDocs on your default browser',
                highlightable=False,
                on_enter=OpenUrlAction("https://devdocs.io/")),
            ExtensionResultItem(
                icon='images/icon.png',
                name='Open cache folder',
                description=
                "Opens the folder where the documentation cache is stored",
                highlightable=False,
                on_enter=OpenAction(self.devdocs_svc.cache_dir)),
            ExtensionResultItem(
                icon='images/icon.png',
                name='Index Documentation',
                description=
                "This process might take a while. You will receive a notification when finished.",
                highlightable=False,
                on_enter=ExtensionCustomAction([]))
        ]

        return RenderResultListAction(items)


class KeywordQueryEventListener(EventListener):
    """ Listener that handles the user input """

    # pylint: disable=unused-argument,no-self-use
    def on_event(self, event, extension):
        """ Handles the event """

        query = event.get_argument() or ""
        keyword = event.get_keyword()

        if query.startswith("!"):
            return extension.show_options_menu(query.strip("!"))

        # If the keyword used is a known keyword, goes directly to the entries
        # page.
        if extension.devdocs_svc.get_doc_by_slug(keyword):
            return extension.show_entries(keyword, query)

        # the individual documentation query format. Ex: php:array_filter
        if query:
            args = query.split(':')

            if len(args) == 2:
                return extension.show_entries(args[0], args[1])

        return extension.list_available_docs(keyword, query)


class PreferencesEventListener(EventListener):
    """
    Listener for prefrences event.
    It is triggered on the extension start with the configured preferences
    """

    def on_event(self, event, extension):
        """ Event handler """
        extension.devdocs_svc.set_docs_to_fetch(event.preferences['docs'])
        extension.index_docs()


class PreferencesUpdateEventListener(EventListener):
    """
    Listener for "Preferences Update" event.
    It is triggered when the user changes any setting in preferences window
    """

    def on_event(self, event, extension):
        """ Event handler """
        if event.id == 'docs':
            extension.devdocs_svc.set_docs_to_fetch(event.new_value)
            extension.index_docs()


class ItemEnterEventListener(EventListener):
    """ Handles Custom ItemEnter event """

    def on_event(self, event, extension):
        """ handle function """
        extension.index_docs()
        return HideWindowAction()


if __name__ == '__main__':
    DevdocsExtension().run()
