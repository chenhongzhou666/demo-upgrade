package handlers

import (
	"bufio"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

type ChordResult struct {
	Symbol    string `json:"symbol"`
	Degree    string `json:"degree"`
	Function  string `json:"function"`
	Inversion int    `json:"inversion"`
	Warning   string `json:"warning,omitempty"`
}

type TimbreResult struct {
	Primary      string         `json:"primary"`
	Distribution map[string]int `json:"distribution"`
}

type FilePaths struct {
	MIDI     string `json:"midi"`
	MusicXML string `json:"musicxml"`
}

type AnalysisResult struct {
	KeyName       string        `json:"key_name"`
	Mode          string        `json:"mode"`
	BPM           float64       `json:"bpm"`
	TimeSig       string        `json:"time_sig"`
	Chords        []ChordResult `json:"chords"`
	Jianpu        string        `json:"jianpu"`
	Timbre        TimbreResult  `json:"timbre"`
	Files         FilePaths     `json:"files"`
	MusicXMLData  string        `json:"musicxml_data,omitempty"` // base64 编码的 MusicXML 内容
}

type ErrorResponse struct {
	Error string `json:"error"`
}

func Analyze(pythonBin, scriptPath string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")

		// 限制上传大小 50MB
		r.Body = http.MaxBytesReader(w, r.Body, 50<<20)

		if err := r.ParseMultipartForm(32 << 20); err != nil {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: fmt.Sprintf("文件太大或格式错误: %v", err),
			})
			return
		}
		defer r.MultipartForm.RemoveAll()

		file, header, err := r.FormFile("audio")
		if err != nil {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: fmt.Sprintf("未找到音频文件: %v", err),
			})
			return
		}
		defer file.Close()

		// 创建临时工作目录
		tmpDir, err := os.MkdirTemp("", "demo-upgrade-*")
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: fmt.Sprintf("创建临时目录失败: %v", err),
			})
			return
		}
		defer os.RemoveAll(tmpDir)

		// 保存上传文件（保留原始扩展名）
		ext := filepath.Ext(header.Filename)
		if ext == "" {
			ext = ".wav"
		}
		inputPath := filepath.Join(tmpDir, "input"+ext)
		dst, err := os.Create(inputPath)
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: fmt.Sprintf("保存文件失败: %v", err),
			})
			return
		}
		if _, err := io.Copy(dst, file); err != nil {
			dst.Close()
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: fmt.Sprintf("写入文件失败: %v", err),
			})
			return
		}
		dst.Close()

		// 手动拍号（可选）
		timeSig := r.FormValue("time_sig")

		// 运行 Python 引擎（120 秒超时）
		ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
		defer cancel()

		engineArgs := []string{scriptPath, inputPath, "--output-dir", tmpDir, "--json"}
		if timeSig != "" {
			engineArgs = append(engineArgs, "--force-ts", timeSig)
		}
		cmd := exec.CommandContext(ctx, pythonBin, engineArgs...)
		cmd.Env = os.Environ()

		stdout, err := cmd.StdoutPipe()
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: fmt.Sprintf("管道创建失败: %v", err),
			})
			return
		}
		stderr, err := cmd.StderrPipe()
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: fmt.Sprintf("管道创建失败: %v", err),
			})
			return
		}

		if err := cmd.Start(); err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: fmt.Sprintf("引擎启动失败: %v", err),
			})
			return
		}

		// 从 stdout 提取 JSON（位于 __JSON_BEGIN__ 和 __JSON_END__ 之间）
		var jsonLines []string
		scanner := bufio.NewScanner(stdout)
		inJSON := false
		for scanner.Scan() {
			line := scanner.Text()
			if line == "__JSON_BEGIN__" {
				inJSON = true
				continue
			}
			if line == "__JSON_END__" {
				inJSON = false
				continue
			}
			if inJSON {
				jsonLines = append(jsonLines, line)
			}
		}

		// 读取 stderr
		errOutput, _ := io.ReadAll(stderr)

		if err := cmd.Wait(); err != nil {
			if ctx.Err() != nil {
				w.WriteHeader(http.StatusRequestTimeout)
				json.NewEncoder(w).Encode(ErrorResponse{
					Error: "分析超时（120秒），请尝试更短的音频",
				})
				return
			}
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: fmt.Sprintf("引擎运行失败: %v\n%s", err, string(errOutput)),
			})
			return
		}

		if len(jsonLines) == 0 {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: "引擎未输出 JSON 结果",
			})
			return
		}

		jsonText := strings.Join(jsonLines, "\n")
		var result AnalysisResult
		if err := json.Unmarshal([]byte(jsonText), &result); err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: fmt.Sprintf("JSON 解析失败: %v", err),
			})
			return
		}

		if result.KeyName == "" {
			w.WriteHeader(http.StatusUnprocessableEntity)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: "未检测到音符，请检查音频内容",
			})
			return
		}

		// 读取 MusicXML 文件内嵌为 base64
		if result.Files.MusicXML != "" {
			if xmlData, err := os.ReadFile(result.Files.MusicXML); err == nil {
				result.MusicXMLData = base64.StdEncoding.EncodeToString(xmlData)
			}
		}

		json.NewEncoder(w).Encode(result)
	}
}
