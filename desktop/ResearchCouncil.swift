import Cocoa
@preconcurrency import WebKit

// A native window around the existing loopback UI. CLI authentication remains in the CLIs.
final class CouncilApp: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    private var window: NSWindow!
    private var web: WKWebView!
    private var status: NSTextField!
    private var spinner: NSProgressIndicator!
    private var starting = false
    private var quitting = false
    private var downloads: Set<WKDownload> = []
    private let port = 8765
    private let serviceLabel = "local.research-council.app"
    private let data = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Research Council", isDirectory: true)
    private var home: URL { URL(string: "http://127.0.0.1:\(port)/index.html")! }
    private var resources: URL { Bundle.main.resourceURL!.appendingPathComponent("council", isDirectory: true) }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        createMenu()
        let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let size = NSSize(width: min(1360, screen.width * 0.94), height: min(900, screen.height * 0.94))
        window = NSWindow(contentRect: NSRect(origin: .zero, size: size), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Research Council"
        window.minSize = NSSize(width: 840, height: 600)
        window.setFrameAutosaveName("ResearchCouncilMainWindow")
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.center()
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        web = WKWebView(frame: .zero, configuration: configuration)
        web.navigationDelegate = self
        web.uiDelegate = self
        web.autoresizingMask = [.width, .height]
        web.frame = window.contentView!.bounds
        window.contentView!.addSubview(web)
        spinner = NSProgressIndicator()
        spinner.style = .spinning
        spinner.translatesAutoresizingMaskIntoConstraints = false
        status = NSTextField(labelWithString: "正在启动 Research Council…")
        status.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(spinner)
        window.contentView!.addSubview(status)
        NSLayoutConstraint.activate([
            spinner.centerXAnchor.constraint(equalTo: window.contentView!.centerXAnchor),
            spinner.centerYAnchor.constraint(equalTo: window.contentView!.centerYAnchor, constant: -20),
            status.centerXAnchor.constraint(equalTo: spinner.centerXAnchor),
            status.topAnchor.constraint(equalTo: spinner.bottomAnchor, constant: 16)
        ])
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        connect()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil)
        if web.url == nil { connect() }
        return true
    }

    private func item(_ title: String, _ action: Selector, _ key: String = "") -> NSMenuItem {
        let entry = NSMenuItem(title: title, action: action, keyEquivalent: key)
        entry.target = self
        return entry
    }
    private func createMenu() {
        let bar = NSMenu()
        let app = NSMenuItem()
        bar.addItem(app)
        let menu = NSMenu()
        menu.addItem(item("关于 Research Council", #selector(about)))
        menu.addItem(.separator())
        menu.addItem(item("显示讨论数据", #selector(revealData)))
        menu.addItem(item("显示运行日志", #selector(revealLog)))
        menu.addItem(.separator())
        menu.addItem(item("退出 Research Council", #selector(quit), "q"))
        app.submenu = menu
        let edit = NSMenuItem()
        edit.title = "编辑"
        let editMenu = NSMenu(title: "编辑")
        for (title, action, key) in [("撤销", "undo:", "z"), ("重做", "redo:", "Z"), ("剪切", "cut:", "x"), ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] {
            editMenu.addItem(NSMenuItem(title: title, action: Selector(action), keyEquivalent: key))
        }
        edit.submenu = editMenu
        bar.addItem(edit)
        let view = NSMenuItem()
        view.title = "窗口"
        let viewMenu = NSMenu(title: "窗口")
        viewMenu.addItem(item("刷新页面", #selector(reload), "r"))
        viewMenu.addItem(item("重新连接本地服务", #selector(reconnect)))
        viewMenu.addItem(item("在默认浏览器中打开", #selector(openBrowser)))
        viewMenu.addItem(.separator())
        viewMenu.addItem(NSMenuItem(title: "最小化", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m"))
        viewMenu.addItem(NSMenuItem(title: "关闭窗口", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w"))
        view.submenu = viewMenu
        bar.addItem(view)
        NSApp.mainMenu = bar
        NSApp.windowsMenu = viewMenu
    }

    // Never mistake another loopback application or another data folder for this app.
    private func probe() async throws -> Bool {
        var request = URLRequest(url: home.deletingLastPathComponent().appendingPathComponent("api/bootstrap"))
        request.timeoutInterval = 2
        let (bytes, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse,
              http.statusCode == 200,
              (http.value(forHTTPHeaderField: "Server") ?? "").hasPrefix("ResearchCouncil/"),
              let body = try JSONSerialization.jsonObject(with: bytes) as? [String: Any],
              let folder = body["dataDirectory"] as? String,
              body["application"] as? String == "research-council" else {
            throw NSError(domain: "ResearchCouncil", code: 1, userInfo: [NSLocalizedDescriptionKey: "端口 8765 已被其他服务或旧版服务占用。请先关闭它，再重新连接。"])
        }
        guard URL(fileURLWithPath: folder).resolvingSymlinksInPath().path == data.resolvingSymlinksInPath().path else {
            throw NSError(domain: "ResearchCouncil", code: 2, userInfo: [NSLocalizedDescriptionKey: "此端口使用的是另一个讨论数据目录。为避免混用数据，应用没有连接。"])
        }
        return true
    }

    private func python() -> String? {
        let candidates = [Bundle.main.object(forInfoDictionaryKey: "RCPythonPath") as? String,
                          "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3",
                          "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
        for path in candidates.compactMap({ $0 }) where FileManager.default.isExecutableFile(atPath: path) {
            let check = Process()
            check.executableURL = URL(fileURLWithPath: path)
            check.arguments = ["-c", "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"]
            check.standardOutput = FileHandle.nullDevice
            check.standardError = FileHandle.nullDevice
            do { try check.run(); check.waitUntilExit(); if check.terminationStatus == 0 { return path } } catch {}
        }
        return nil
    }

    private func startService() throws {
        guard let interpreter = python() else {
            throw NSError(domain: "ResearchCouncil", code: 3, userInfo: [NSLocalizedDescriptionKey: "未找到 Python 3.11 或以上版本。请先安装 Python，再打开应用。"])
        }
        try FileManager.default.createDirectory(at: data, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let command = Process()
        command.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        command.arguments = ["submit", "-l", serviceLabel, "-o", data.appendingPathComponent("server.log").path,
                             "-e", data.appendingPathComponent("server-error.log").path, "--", "/usr/bin/env", "PYTHONDONTWRITEBYTECODE=1", interpreter, "-B",
                             resources.appendingPathComponent("bridge.py").path, "--no-browser", "--data-dir", data.path, "--port", String(port)]
        command.standardOutput = FileHandle.nullDevice
        command.standardError = FileHandle.nullDevice
        try command.run()
        command.waitUntilExit()
        // An existing label may be starting already. The health check determines success.
    }

    @MainActor private func connect() {
        guard !starting else { return }
        starting = true
        spinner.isHidden = false
        status.isHidden = false
        status.stringValue = "正在启动 Research Council…"
        spinner.startAnimation(nil)
        Task {
            do {
                var available = false
                do { available = try await probe() }
                catch let error as NSError where error.domain == NSURLErrorDomain {
                    if ![NSURLErrorCannotConnectToHost, NSURLErrorNetworkConnectionLost].contains(error.code) { throw error }
                }
                if !available {
                    try startService()
                    for _ in 0..<60 {
                        try await Task.sleep(nanoseconds: 250_000_000)
                        do { if try await probe() { available = true; break } }
                        catch let error as NSError where error.domain == NSURLErrorDomain { continue }
                    }
                }
                guard available else { throw NSError(domain: "ResearchCouncil", code: 4, userInfo: [NSLocalizedDescriptionKey: "本地服务未能启动。请在应用菜单中打开运行日志查看原因。"] ) }
                web.load(URLRequest(url: home))
            } catch { showError(error.localizedDescription) }
            starting = false
        }
    }

    private func showError(_ text: String) {
        spinner.stopAnimation(nil)
        spinner.isHidden = true
        status.stringValue = text
        let alert = NSAlert()
        alert.messageText = "Research Council 暂时无法启动"
        alert.informativeText = text
        alert.addButton(withTitle: "重试")
        alert.addButton(withTitle: "查看日志")
        alert.addButton(withTitle: "取消")
        alert.beginSheetModal(for: window) { response in
            if response == .alertFirstButtonReturn { self.connect() }
            else if response == .alertSecondButtonReturn { self.revealLog() }
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        spinner.stopAnimation(nil)
        spinner.isHidden = true
        status.isHidden = true
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { if (error as NSError).code != NSURLErrorCancelled { showError(error.localizedDescription) } }
    private func isLocal(_ url: URL) -> Bool { url.scheme == "http" && url.host == "127.0.0.1" && url.port == port }
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if action.shouldPerformDownload { decisionHandler(.download); return }
        if isLocal(url) || url.scheme == "about" || url.scheme == "blob" { decisionHandler(.allow); return }
        decisionHandler(.cancel)
        if action.targetFrame?.isMainFrame != false && ["http", "https", "mailto"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url {
            if isLocal(url) { web.load(URLRequest(url: url)) }
            else if ["http", "https", "mailto"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        }
        return nil
    }
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.canChooseFiles = !parameters.allowsDirectories
        panel.beginSheetModal(for: window) { completionHandler($0 == .OK ? panel.urls : nil) }
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        downloads.insert(download)
        download.delegate = self
    }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        downloads.insert(download)
        download.delegate = self
    }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = suggestedFilename
        panel.beginSheetModal(for: window) { completionHandler($0 == .OK ? panel.url : nil) }
    }
    func downloadDidFinish(_ download: WKDownload) { downloads.remove(download) }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        downloads.remove(download)
        if (error as NSError).code != NSURLErrorCancelled { showError("导出失败："+error.localizedDescription) }
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert(); alert.messageText = message
        alert.beginSheetModal(for: window) { _ in completionHandler() }
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert(); alert.messageText = message
        alert.addButton(withTitle: "确认"); alert.addButton(withTitle: "取消")
        alert.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn) }
    }
    @objc private func reload() { web.reload() }
    @objc private func reconnect() { connect() }
    @objc private func openBrowser() { NSWorkspace.shared.open(home) }
    @objc private func revealData() { NSWorkspace.shared.open(data) }
    @objc private func revealLog() { NSWorkspace.shared.activateFileViewerSelecting([data.appendingPathComponent("server-error.log")]) }
    @objc private func about() { NSApp.orderFrontStandardAboutPanel(options: [.applicationName: "Research Council", .applicationVersion: "0.11", .credits: NSAttributedString(string: "本地研究讨论 · Claude Code / Codex / Gemini\n关闭窗口或退出应用后，已启动的本地讨论服务继续运行。")]) }
    @objc private func quit() { NSApp.terminate(nil) }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard !quitting, web != nil else { return .terminateNow }
        quitting = true
        var replied = false
        let reply = { if !replied { replied = true; sender.reply(toApplicationShouldTerminate: true) } }
        web.callAsyncJavaScript("if (window.CouncilBridge) await window.CouncilBridge.flush(); return true", arguments: [:], in: nil, in: .page) { _ in reply() }
        DispatchQueue.main.asyncAfter(deadline: .now()+3, execute: reply)
        return .terminateLater
    }
}

let app = NSApplication.shared
let delegate = CouncilApp()
app.delegate = delegate
app.run()
