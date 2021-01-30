# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
import schedule
from octoprint.settings import settings
from octoprint.server.util.flask import restricted_access
from octoprint.util.comm import process_gcode_line
from octoprint.util import RepeatedTimer

import flask
import json
import os.path


class PlaylistPlugin(octoprint.plugin.TemplatePlugin,
					 octoprint.plugin.SettingsPlugin,
					 octoprint.plugin.AssetPlugin,
					 octoprint.plugin.BlueprintPlugin,
					 octoprint.plugin.EventHandlerPlugin):
	_playlist = []
	_current_file = ""
	_repeatedtimer = None
	_print_completed = False
	_uploads_dir = settings().getBaseFolder("uploads")

	_insert_bed_clear_script = False  # set after ending a print when there are still prints in the queue
	_stripping_start = False  # set after completion of first print in queue
	_stripping_end = False  # unset after completion of any print

	# these are initialised when printing a file from the queue
	_strip_start_marker = ""
	_strip_end_marker = ""

	_process_gcode_line_super = None

	# BluePrintPlugin (api requests)
	@octoprint.plugin.BlueprintPlugin.route("/queue", methods=["GET"])
	def get_queue(self):
		self._logger.info("getting queue")
		return flask.jsonify(playlist=self._settings.get(["playlist"]))

	@octoprint.plugin.BlueprintPlugin.route("/queue", methods=["POST"])
	@restricted_access
	def set_queue(self):
		self._logger.info("received print queue from frontend")
		last_playlist = self._playlist[:]

		self._playlist = []
		for v in flask.request.form:
			j = json.loads(v)
			for p in j:
				self._playlist.append(p)

		state = self._printer.get_state_id()
		if state in ["PRINTING", "PAUSED"]:
			# keep the currently active job on the top of the queue
			active_file = self._printer.get_current_job()["file"]["path"]
			if not self._playlist or self._playlist[0]["fileName"] != active_file:
				try:
					self._playlist.remove(active_file)
				except ValueError:
					pass
				self._playlist.insert(0, active_file)
				if self._playlist == last_playlist:
					# force correcting the queue on the originating client
					last_playlist = []

		if self._playlist != last_playlist:
			self._send_queue_to_clients()

		if state == "OPERATIONAL" and self._settings.get(["auto_start_queue"]):
			self._print_from_queue()

		return flask.make_response("POST successful", 200)

	@octoprint.plugin.BlueprintPlugin.route("/start", methods=["POST"])
	@restricted_access
	def start_queue(self):
		self._playlist = []
		for v in flask.request.form:
			j = json.loads(v)
			for p in j:
				self._playlist += [p]

		self._print_from_queue()

		return flask.make_response("POST successful", 200)

	def _print_from_queue(self):
		if len(self._playlist) > 0:
			self._logger.info(self._playlist)
			self._current_file = self._playlist[0]["id"]
			f = os.path.join(self._uploads_dir, self._playlist[0]["fileName"])
			self._logger.info("attempting to select and print file: " + f)
			# self._settings.set(['playlist'], [self._playlist])
			self._printer.select_file(f, False, True)

	def _send_queue_to_clients(self):
		self._plugin_manager.send_plugin_message(self._identifier, dict(
			type="set_queue",
			playlist=self._playlist,
			current_file=self._current_file
		))

	def _create_and_print_queue(self):
		self._logger.info("Starting scheduled print queue.")
		self._playlist = self._settings.get(["playlist"])
		self._logger.info("%s" % self._playlist)
		self._print_from_queue()

	def _pause_print_queue(self):
		if self._printer.is_printing() and len(self._playlist) > 0:
			self._logger.info("Pausing print queue.")
			self._printer.pause_print()

	def _resume_print_queue(self):
		if self._printer.is_paused() and len(self._playlist) > 0:
			self._logger.info("Resuming print queue.")
			self._printer.resume_print()

	# SettingPlugin
	def get_settings_defaults(self):
		return dict(
			bed_clear_script="",
			strip_start_marker="",
			strip_end_marker="",
			auto_start_queue=False,
			auto_queue_files=False,
			playlist=[],
			start_time="",
			blackout_start_time="",
			blackout_stop_time="",
			auto_repeat_queue=False
		)

	# TemplatePlugin
	def get_template_configs(self):
		return [
			dict(type="settings", custom_bindings=False, template="playlist_settings.jinja2"),
		]

	# AssetPlugin
	def get_assets(self):
		return dict(js=["js/jquery-ui.min.js", "js/knockout-sortable.js", "js/playlist.js"])

	# Hooks
	def alter_start_and_end_gcode(self, comm_instance, phase, cmd, cmd_type, gcode, subcode=None, tags=None, *args,
								  **kwargs):
		if self._insert_bed_clear_script:
			self._insert_bed_clear_script = False
			bed_clear_script = self._settings.get(["bed_clear_script"])
			bed_clear_script_lines = [process_gcode_line(l) for l in bed_clear_script.splitlines()]
			result = [(l,) for l in bed_clear_script_lines if l is not None]

			if not self._stripping_start:
				result.append((cmd,))

			if not result:
				result = (None,)

			return result

		if self._stripping_start:
			print("stripped from start: %s" % cmd)
			return None,  # strip this line

		if self._stripping_end:
			print("stripped from end: %s" % cmd)
			return None,  # strip this line

		return  # leave gcode as is

	# NB: Here be dragons!
	# This is a hack to get at the gcode line before comments are stripped
	def _patch_current_file_process(self):
		if not self._printer._comm._currentFile or self._printer._comm._currentFile._process == self._process_gcode_line:
			return

		self._process_gcode_line_super = self._printer._comm._currentFile._process
		self._printer._comm._currentFile._process = self._process_gcode_line

	def _process_gcode_line(self, line, offsets, current_tool):
		stripped_line = line.rstrip()

		if self._strip_start_marker and stripped_line == self._strip_start_marker:
			self._logger.info("start mark found")
			self._stripping_start = False
		elif self._strip_end_marker and stripped_line == self._strip_end_marker and len(self._playlist) > 1:
			self._logger.info("end mark found")
			self._stripping_end = True

		return self._process_gcode_line_super(line, offsets=offsets, current_tool=current_tool)

	# Event Handling
	def on_event(self, event, payload):
		if event in ("Startup", "SettingsUpdated"):
			self._logger.info("Clearing scheduled jobs.")
			schedule.clear("playlist")
			schedule.clear("blackout_start_time")
			schedule.clear("blackout_stop_time")
			if self._settings.get(["auto_start_queue"]) and self._settings.get(["start_time"]) != "":
				self._logger.info("Scheduling print queue for %s." % self._settings.get(["start_time"]))
				schedule.every().day.at(self._settings.get(["start_time"])).do(self._create_and_print_queue).tag(
					"playlist")

			if self._settings.get(["blackout_start_time"]) and self._settings.get(["blackout_start_time"]) != "":
				self._logger.info("Scheduling blackout start for %s." % self._settings.get(["blackout_start_time"]))
				schedule.every().day.at(self._settings.get(["blackout_start_time"])).do(self._pause_print_queue).tag(
					"blackout_start_time")

			if self._settings.get(["blackout_stop_time"]) and self._settings.get(["blackout_stop_time"]) != "":
				self._logger.info("Scheduling blackout stop for %s." % self._settings.get(["blackout_stop_time"]))
				schedule.every().day.at(self._settings.get(["blackout_stop_time"])).do(self._resume_print_queue).tag(
					"blackout_stop_time")

			if not self._repeatedtimer:
				self._repeatedtimer = RepeatedTimer(60, schedule.run_pending)
				self._repeatedtimer.start()

			if len(self._playlist) > 0:
				self._logger.info("Updating currently running playlist.")
				add_file = False
				self._playlist = []
				for file in self._settings.get(["playlist"]):
					if file["id"] == self._current_file:
						add_file = True
					if add_file:
						self._playlist.append(file)

		if event == "ClientOpened":
			self._send_queue_to_clients()

		if event == "FileAdded":
			if self._settings.get(["auto_queue_files"]):
				self._playlist.append(payload["path"])
				self._send_queue_to_clients()

		if event == "FileRemoved":
			new_queue = [f for f in self._playlist if f != payload["path"]]
			new_queues = [f for f in self._settings.get(["playlist"]) if f["fileName"] != payload["path"]]
			if new_queues != self._settings.get(["playlist"]):
				self._settings.set(["playlist"], new_queues)
				self._playlist = new_queue
				self._settings.save()
				self._plugin_manager.send_plugin_message(self._identifier, dict(
					type="file_removed",
					playlist=new_queues,
					removed_file=payload["path"]
				))

		if event == "FileSelected":
			self._patch_current_file_process()

		if event == "PrintStarted":
			# initialise these here in case the settings have changed
			self._strip_start_marker = self._settings.get(["strip_start_marker"])
			self._strip_end_marker = self._settings.get(["strip_end_marker"])

			self._print_completed = False

			if not self._playlist or self._playlist[0]["fileName"] != payload["path"]:
				self._playlist.insert(0, dict(fileName=payload["path"], id="0"))
				self._send_queue_to_clients()
			if len(self._playlist) > 0:
				self._current_file = self._playlist[0]["id"]
				self._send_queue_to_clients()

		if event in "PrintDone":
			self._print_completed = True
			self._stripping_start = False
			self._stripping_end = False

		if event == "PrinterStateChanged":
			state = self._printer.get_state_id()
			self._logger.info("printer state: " + state)

			if state == "OPERATIONAL":
				self._stripping_start = False
				self._stripping_end = False

				if len(self._playlist) > 0:
					self._playlist.pop(0)
					if len(self._playlist) == 0:
						self._current_file = ""
					self._send_queue_to_clients()

					if len(self._playlist) > 0:
						if self._strip_start_marker != "":
							self._stripping_start = True
						self._insert_bed_clear_script = True
						self._print_from_queue()
					elif len(self._playlist) == 0:
						if self._settings.get_boolean(["auto_repeat_queue"]):
							self._logger.info("Restarting print queue from beginning.")
							self._create_and_print_queue()

		return

	def get_update_information(self):
		return dict(
			playlist=dict(
				displayName="Playlist",
				displayVersion=self._plugin_version,

				# version check: github repository
				type="github_release",
				user="jneilliii",
				repo="OctoPrint-Playlist",
				current=self._plugin_version,
				stable_branch=dict(
					name="Stable", branch="master", comittish=["master"]
				),
				prerelease_branches=[
					dict(
						name="Release Candidate",
						branch="rc",
						comittish=["rc", "master"],
					)
				],

				# update method: pip
				pip="https://github.com/jneilliii/OctoPrint-Playlist/releases/latest/download/{target_version}.zip"
			)
		)


__plugin_name__ = "Playlist"
__plugin_pythoncompat__ = ">=2.7,<4"


def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = PlaylistPlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.comm.protocol.gcode.queuing": __plugin_implementation__.alter_start_and_end_gcode,
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
	}
