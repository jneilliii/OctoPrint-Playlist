/*
 * View model for OctoPrint-Print-Queue
 *
 * Author: Michael New
 * License: AGPLv3
 */

$(function() {
	function PlaylistViewModel(parameters) {
		var self = this;

		self.printerState = parameters[0];
		self.loginState = parameters[1];
		self.files = parameters[2];
		self.settings = parameters[3];

		self.queuedPrints = ko.observableArray();
		self.current_file = ko.observable();
		self.flatPrintQueue = ko.computed(function() {
				var files = ko.utils.arrayMap(self.queuedPrints(), function(item) {
					return item.fileName();
				});
				return files;
			},self);

		self.currentlyPrintingQueue = false;

		self.autoStartQueue = ko.observable(false);
		self.autoQueueFiles = ko.observable(false);
		self.start_time = ko.observable();
		self.auto_repeat_queue = ko.observable(false);

		self.onBeforeBinding = function() {
			self.queuedPrints(self.settings.settings.plugins.playlist.playlist());
			self.queuedPrints.subscribe(function(changes) {
				self.settings.saveData({
					plugins: {
						playlist: {
							playlist: ko.toJS(self.queuedPrints())
						}
					}
				});
			});

			self.autoStartQueue(self.settings.settings.plugins.playlist.auto_start_queue());
			self.settings.settings.plugins.playlist.auto_start_queue.subscribe(function(data) {
				if (self.autoStartQueue() != data) {
					self.autoStartQueue(data);
				}
			});

			self.autoStartQueue.subscribe(function(checked) {
				self.settings.saveData({
					plugins: {
						playlist: {
							auto_start_queue: checked
						}
					}
				});
			});

			self.autoQueueFiles(self.settings.settings.plugins.playlist.auto_queue_files());
			self.settings.settings.plugins.playlist.auto_queue_files.subscribe(function(data) {
				if (self.autoQueueFiles() != data) {
					self.autoQueueFiles(data);
				}
			});

			self.autoQueueFiles.subscribe(function(checked) {
				self.settings.saveData({
					plugins: {
						playlist: {
							auto_queue_files: checked
						}
					}
				});
			});

			self.start_time(self.settings.settings.plugins.playlist.start_time());
			self.settings.settings.plugins.playlist.start_time.subscribe(function(data) {
				if (self.start_time() != data) {
					self.start_time(data);
				}
			});

			self.start_time.subscribe(function(data) {
				self.settings.saveData({
					plugins: {
						playlist: {
							start_time: data
						}
					}
				});
			});

			self.auto_repeat_queue(self.settings.settings.plugins.playlist.auto_repeat_queue());
			self.settings.settings.plugins.playlist.auto_repeat_queue.subscribe(function(data) {
				if (self.auto_repeat_queue() != data) {
					self.auto_repeat_queue(data);
				}
			});

			self.auto_repeat_queue.subscribe(function(checked) {
				self.settings.saveData({
					plugins: {
						playlist: {
							auto_repeat_queue: checked
						}
					}
				});
			});
		}

		self.get_print_time = function(data) {
			var t = data.statistics ? data.statistics.averagePrintTime["_default"] : data.gcodeAnalysis ? data.gcodeAnalysis["estimatedPrintTime"] : '',
				d = Math.floor(t/86400),
				h = ('0'+Math.floor(t/3600) % 24).slice(-2),
				m = ('0'+Math.floor(t/60)%60).slice(-2),
				s = ('0' + t % 60).slice(-2);
			return (d>0?d+':':'00:')+(h>0?h+':':'00:')+(m>0?m+':':'00:')+(s>0?s:'00');
		}

		self.files.addToPlaylist = function(data) {
			var file_count = ko.utils.arrayFilter(self.queuedPrints(), function(file) {return file.fileName() == data["path"];}).length;
			self.queuedPrints.push({id: ko.observable(md5(data["origin"] + ":" + data["path"] + ":" + file_count)), fileName: ko.observable(data["path"]), print_time: ko.observable(self.get_print_time(data))});
		}

		$(document).ready(function(){
			let regex = /<div class="btn-group action-buttons">([\s\S]*)<.div>/mi;
			let template = '<div class="btn btn-mini" data-bind="click: function() { if ($root.loginState.isUser()) { $root.addToPlaylist($data) } else { return; } }, css: {disabled: !$root.loginState.isUser()}" title="Add to Playlist"><i class="fa fa-list"></i></div>';

			$("#files_template_machinecode").text(function () {
				return $(this).text().replace(regex, '<div class="btn-group action-buttons">$1	' + template + '></div>');
			});
		});

		self.startQueue = function() {
			console.log(self.queuedPrints());
			console.log(self.flatPrintQueue());
			self.currentlyPrintingQueue = true;
			$.ajax({
				url: "plugin/playlist/start",
				type: "POST",
				dataType: "json",
				headers: {
					"X-Api-Key":UI_API_KEY,
				},
				data: ko.toJSON(self.queuedPrints())
			});
		}

		self.clearQueue = function() {
			self.queuedPrints.removeAll();
		}

		self.moveJobUp = function(data) {
			let currentIndex = self.queuedPrints.indexOf(data);
			if (currentIndex > 0) {
				let queueArray = self.queuedPrints();
				self.queuedPrints.splice(currentIndex-1, 2, queueArray[currentIndex], queueArray[currentIndex - 1]);
			}
		}

		self.moveJobDown = function(data) {
			let currentIndex = self.queuedPrints.indexOf(data);
			if (currentIndex < self.queuedPrints().length - 1) {
				let queueArray = self.queuedPrints();
				self.queuedPrints.splice(currentIndex, 2, queueArray[currentIndex + 1], queueArray[currentIndex]);
			}
		}

		self.removeJob = function(data) {
			self.queuedPrints.remove(data);
		}

		self.onDataUpdaterPluginMessage = function(plugin, data) {
			// if the "add file" field is blank and the user loads a new file
			// put it's name into the text field
			if (plugin != "playlist") {
				return;
			}

			switch(data["type"]) {
				case "set_queue":
					if(data.current_file !== self.current_file()){
						self.current_file(data.current_file);
					}
					if(data.playlist.length == 0){
						if(self.currentlyPrintingQueue){
							self.currentlyPrintingQueue = false;
							if (data.current_file !== ""){
								new PNotify({
										title: 'Playlist',
										text: 'Playlist completed.',
										type: 'info',
										hide: true,
										buttons: {
											closer: true,
											sticker: false
										}
									});
							}
						}
					} else {
						self.currentlyPrintingQueue = true;
					}
					break;
				case "file_removed":
					if(data.removed_file.length > 0) {
						var new_queue = ko.utils.arrayFilter(self.queuedPrints(), function(file) {return file.fileName() !== data["removed_file"];});
						if(new_queue !== self.queuedPrints()){
							console.log('Received updated queue from server, resetting view.');
							self.queuedPrints(new_queue);
						}
					}
					break;
			}
		}
	}

	// This is how our plugin registers itself with the application, by adding some configuration
	// information to the global variable OCTOPRINT_VIEWMODELS
	OCTOPRINT_VIEWMODELS.push([
		// This is the constructor to call for instantiating the plugin
		PlaylistViewModel,

		// This is a list of dependencies to inject into the plugin, the order which you request
		// here is the order in which the dependencies will be injected into your view model upon
		// instantiation via the parameters argument
		["printerStateViewModel", "loginStateViewModel", "filesViewModel", "settingsViewModel"],

		// Finally, this is the list of selectors for all elements we want this view model to be bound to.
		["#tab_plugin_playlist"]
	]);
});
