import Foundation

/// 持久化服务器地址（iPad 上用 Mac 的局域网 IP）
struct ServerConfig {
    private static let hostKey = "server_host"
    private static let defaults = UserDefaults.standard

    static var host: String {
        get { defaults.string(forKey: hostKey) ?? "localhost" }
        set { defaults.set(newValue, forKey: hostKey) }
    }

    static var baseURL: String {
        "http://\(host):8090"
    }
}
