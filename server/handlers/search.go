package handlers

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"demo-upgrade/server/search"
)

// FingerprintOutput Python 指纹提取脚本的 JSON 输出
type FingerprintOutput struct {
	Intervals  []int            `json:"intervals"`
	TotalNotes int              `json:"total_notes"`
	NgramSize  int              `json:"ngram_size"`
	HashCount  int              `json:"hash_count"`
	Hashes     []search.HashEntry `json:"hashes"`
	Source     string           `json:"source"`
	Error      string           `json:"error,omitempty"`
}

// Search 返回搜索处理器（依赖已加载的索引）
func Search(pythonBin, enginePath string, idx *search.Index) http.HandlerFunc {
	fingerprintScript := filepath.Join(enginePath, "extract_fingerprint.py")

	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")

		// 限制上传 50MB
		r.Body = http.MaxBytesReader(w, r.Body, 50<<20)
		if err := r.ParseMultipartForm(32 << 20); err != nil {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: fmt.Sprintf("文件太大: %v", err),
			})
			return
		}
		defer r.MultipartForm.RemoveAll()

		file, header, err := r.FormFile("audio")
		if err != nil {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: "缺少 audio 字段",
			})
			return
		}
		defer file.Close()

		// 保存上传文件
		tmpDir, err := os.MkdirTemp("", "demo-search-*")
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(ErrorResponse{Error: "临时目录创建失败"})
			return
		}
		defer os.RemoveAll(tmpDir)

		ext := filepath.Ext(header.Filename)
		if ext == "" {
			ext = ".wav"
		}
		inputPath := filepath.Join(tmpDir, "input"+ext)
		dst, _ := os.Create(inputPath)
		io.Copy(dst, file)
		dst.Close()

		// 运行指纹提取脚本 (60s 超时)
		ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
		defer cancel()

		cmd := exec.CommandContext(ctx, pythonBin, fingerprintScript, inputPath)
		cmd.Env = os.Environ()

		stdout, _ := cmd.StdoutPipe()
		stderr, _ := cmd.StderrPipe()

		if err := cmd.Start(); err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: fmt.Sprintf("指纹提取启动失败: %v", err),
			})
			return
		}

		var outLines []string
		scanner := bufio.NewScanner(stdout)
		for scanner.Scan() {
			outLines = append(outLines, scanner.Text())
		}
		errOutput, _ := io.ReadAll(stderr)

		if err := cmd.Wait(); err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: fmt.Sprintf("指纹提取失败: %v\n%s", err, string(errOutput)),
			})
			return
		}

		if len(outLines) == 0 {
			w.WriteHeader(http.StatusUnprocessableEntity)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: "未检测到音符，无法提取指纹",
			})
			return
		}

		// 解析指纹 JSON
		var fp FingerprintOutput
		if err := json.Unmarshal([]byte(strings.Join(outLines, "\n")), &fp); err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: fmt.Sprintf("指纹 JSON 解析失败: %v", err),
			})
			return
		}

		if fp.Error != "" {
			w.WriteHeader(http.StatusUnprocessableEntity)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: fp.Error,
			})
			return
		}

		if len(fp.Hashes) == 0 {
			w.WriteHeader(http.StatusUnprocessableEntity)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: "音符太少，无法生成指纹（至少需要 4 个音符）",
			})
			return
		}

		// 搜索索引
		results := idx.Search(fp.Hashes)

		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"query": map[string]interface{}{
				"total_notes": fp.TotalNotes,
				"hash_count":  fp.HashCount,
				"ngram_size":  fp.NgramSize,
			},
			"results": results,
			"library_size": len(idx.Tracks),
		})
	}
}
