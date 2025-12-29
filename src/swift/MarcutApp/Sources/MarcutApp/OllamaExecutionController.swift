import Foundation

enum OllamaExecutionStrategy: String, CaseIterable {
    case direct
}

final class OllamaExecutionController {
    private let strategy: OllamaExecutionStrategy

    init(strategy: OllamaExecutionStrategy = .direct) {
        self.strategy = strategy
    }

    func selectedStrategy() -> OllamaExecutionStrategy {
        strategy
    }

    func executeWithOllama<T>(
        ollamaBinaryPath: String,
        ollamaHost: String,
        timeout: TimeInterval,
        operation: @escaping (Process) throws -> T
    ) throws -> T {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: ollamaBinaryPath)
        process.environment = ["OLLAMA_HOST": ollamaHost]

        let result = try operation(process)
        return result
    }
}
