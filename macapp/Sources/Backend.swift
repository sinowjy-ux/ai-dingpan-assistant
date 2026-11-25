import Foundation

/// 在后台启动 ~/stock_platform/server.py（私有端口），App 退出时一并关闭。
final class Backend {
    static let shared = Backend()
    /// 发布版：安装包里自带程序代码（Resources/app）和 Python（Resources/python-arm64 / python-x86_64）
    let bundledApp: String? = {
        guard let r = Bundle.main.resourcePath else { return nil }
        return FileManager.default.fileExists(atPath: r + "/app/server.py") ? r + "/app" : nil
    }()
    var isBundled: Bool { bundledApp != nil }
    lazy var port: Int = Int(ProcessInfo.processInfo.environment["AIDP_PORT"] ?? "") ?? (isBundled ? 8798 : 8797)
    var base: URL { URL(string: "http://127.0.0.1:\(port)")! }
    private var proc: Process?

    /// 数据目录：发布版放在 ~/Library/Application Support/AI盯盘助手/app（程序代码每次启动从安装包同步，数据和缓存保留）
    var root: String {
        if let r = ProcessInfo.processInfo.environment["AIDP_ROOT"] { return r }
        if isBundled { return NSHomeDirectory() + "/Library/Application Support/AI盯盘助手/app" }
        // 从源码构建时，build.sh 把仓库位置写进 Resources/source_root.txt
        if let r = Bundle.main.path(forResource: "source_root", ofType: "txt"),
           let t = try? String(contentsOfFile: r, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines),
           FileManager.default.fileExists(atPath: t + "/server.py") { return t }
        return NSHomeDirectory() + "/stock_platform"
    }

    func findPython() -> String? {
        if isBundled, let r = Bundle.main.resourcePath {
            #if arch(arm64)
            let p = r + "/python-arm64/bin/python3"
            #else
            let p = r + "/python-x86_64/bin/python3"
            #endif
            if FileManager.default.isExecutableFile(atPath: p) { return p }
        }
        let cands = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3",
                     "/Library/Frameworks/Python.framework/Versions/Current/bin/python3", "/usr/bin/python3"]
        return cands.first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    /// 发布版：把安装包里的程序代码同步到数据目录（ditto 只覆盖同名文件，已下载的行情、数据库都保留）
    func syncBundledCode() throws {
        guard let src = bundledApp else { return }
        try FileManager.default.createDirectory(atPath: root, withIntermediateDirectories: true)
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
        p.arguments = [src, root]
        try p.run()
        p.waitUntilExit()
    }

    func ping() async -> Bool {
        var req = URLRequest(url: base.appendingPathComponent("api/monitor/meta"))
        req.timeoutInterval = 3
        guard let (_, r) = try? await URLSession.shared.data(for: req), let h = r as? HTTPURLResponse else { return false }
        return h.statusCode == 200
    }

    /// 已在运行则复用；否则启动并等待就绪。
    func start() async throws {
        if await ping() { return }
        try syncBundledCode()
        guard FileManager.default.fileExists(atPath: root + "/server.py") else {
            throw NSError(domain: "AIDP", code: 1, userInfo: [NSLocalizedDescriptionKey: "找不到 \(root)/server.py"])
        }
        guard let py = findPython() else {
            throw NSError(domain: "AIDP", code: 2, userInfo: [NSLocalizedDescriptionKey: "找不到 python3"])
        }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: py)
        p.arguments = ["-u", root + "/server.py"]
        p.currentDirectoryURL = URL(fileURLWithPath: root)
        var env = ProcessInfo.processInfo.environment
        env["PORT"] = String(port)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONNOUSERSITE"] = "1"
        p.environment = env
        let logDir = NSHomeDirectory() + "/Library/Logs"
        try? FileManager.default.createDirectory(atPath: logDir, withIntermediateDirectories: true)
        let logPath = logDir + (isBundled ? "/AI盯盘助手.log" : "/AI盯盘.log")
        FileManager.default.createFile(atPath: logPath, contents: nil)
        if let fh = FileHandle(forWritingAtPath: logPath) { p.standardOutput = fh; p.standardError = fh }
        try p.run()
        proc = p
        for _ in 0..<60 {
            try await Task.sleep(nanoseconds: 250_000_000)
            if await ping() { return }
            if !p.isRunning { break }
        }
        throw NSError(domain: "AIDP", code: 3, userInfo: [NSLocalizedDescriptionKey: "后台引擎没有启动成功，日志：\(logPath)"])
    }

    func stop() {
        if let p = proc, p.isRunning { p.terminate() }
    }

    func get<T: Decodable>(_ path: String, _ type: T.Type, timeout: TimeInterval = 120) async throws -> T {
        var req = URLRequest(url: URL(string: base.absoluteString + path)!)
        req.timeoutInterval = timeout
        let (data, resp) = try await URLSession.shared.data(for: req)
        if let h = resp as? HTTPURLResponse, h.statusCode != 200 {
            let msg = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["error"] as? String
            throw NSError(domain: "AIDP", code: h.statusCode, userInfo: [NSLocalizedDescriptionKey: msg ?? "HTTP \(h.statusCode)"])
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
}
