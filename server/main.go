package main

import (
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"

	"demo-upgrade/server/handlers"
	"demo-upgrade/server/middleware"
)

func findEnginePath() string {
	// 1. 环境变量覆盖
	if p := os.Getenv("ENGINE_PATH"); p != "" {
		if _, err := os.Stat(filepath.Join(p, ".venv-p2/bin/python3")); err == nil {
			return p
		}
	}

	// 2. 相对于服务器二进制所在目录
	if exe, err := os.Executable(); err == nil {
		candidate := filepath.Join(filepath.Dir(exe), "..", "..", "..", "engine")
		if _, err := os.Stat(filepath.Join(candidate, ".venv-p2/bin/python3")); err == nil {
			return candidate
		}
	}

	// 3. 硬编码默认路径
	home, _ := os.UserHomeDir()
	return filepath.Join(home, "Desktop/Demo独自升级/engine")
}

func main() {
	enginePath := findEnginePath()
	pythonBin := filepath.Join(enginePath, ".venv-p2/bin/python3")
	scriptPath := filepath.Join(enginePath, "verify_pipeline.py")

	if _, err := os.Stat(pythonBin); err != nil {
		log.Fatalf("❌ Python 引擎未找到: %s\n   请确认引擎目录存在且已安装依赖", pythonBin)
	}
	if _, err := os.Stat(scriptPath); err != nil {
		log.Fatalf("❌ 引擎脚本未找到: %s", scriptPath)
	}

	mux := http.NewServeMux()

	mux.HandleFunc("GET /api/health", handlers.Health(enginePath))

	analyzeHandler := handlers.Analyze(pythonBin, scriptPath)
	mux.HandleFunc("POST /api/analyze", analyzeHandler)

	handler := middleware.Logging(mux)

	port := "8090"
	fmt.Println("━━━ Demo 独自升级 · API Server ━━━")
	fmt.Printf("引擎路径: %s\n", enginePath)
	fmt.Printf("Python:   %s\n", pythonBin)
	fmt.Printf("端口:     %s\n", port)
	fmt.Printf("启动成功: http://localhost:%s\n", port)

	if err := http.ListenAndServe(":"+port, handler); err != nil {
		log.Fatalf("服务器启动失败: %v", err)
	}
}
