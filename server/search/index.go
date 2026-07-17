package search

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"sort"
)

// TrackInfo 曲目信息
type TrackInfo struct {
	ID       string `json:"id"`       // 唯一标识
	Title    string `json:"title"`    // 曲名
	Composer string `json:"composer"` // 作曲家
	KeyName  string `json:"key_name"` // 调性, 如 "C major"
}

// HashEntry 指纹哈希条目
type HashEntry struct {
	Index int   `json:"index"` // 在音程序列中的位置
	Hash  uint64 `json:"hash"` // n-gram 哈希值
}

// TrackFingerprint 一首曲子的完整指纹
type TrackFingerprint struct {
	Track      TrackInfo   `json:"track"`
	Intervals  []int       `json:"intervals"`
	TotalNotes int         `json:"total_notes"`
	NgramSize  int         `json:"ngram_size"`
	HashCount  int         `json:"hash_count"`
	Hashes     []HashEntry `json:"hashes"`
}

// Index 倒排索引: hash → [(trackIdx, offsetInTrack)]
type Index struct {
	Tracks []TrackFingerprint
	m      map[uint64][]Match
}

// Match 一次哈希匹配
type Match struct {
	TrackIdx int // tracks 数组索引
	Offset   int // 哈希在曲中的位置
}

// SearchResult 搜索结果
type SearchResult struct {
	Track       TrackInfo `json:"track"`
	MatchCount  int       `json:"match_count"`
	Containment float64   `json:"containment"`
	Jaccard     float64   `json:"jaccard"`
}

// LoadIndex 从 JSON 文件加载指纹库
func LoadIndex(path string) (*Index, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("读取索引文件失败: %w", err)
	}

	var tracks []TrackFingerprint
	if err := json.Unmarshal(data, &tracks); err != nil {
		return nil, fmt.Errorf("解析索引 JSON 失败: %w", err)
	}

	idx := &Index{
		Tracks: tracks,
		m:      make(map[uint64][]Match),
	}

	// 构建倒排索引
	for ti, track := range tracks {
		for _, entry := range track.Hashes {
			idx.m[entry.Hash] = append(idx.m[entry.Hash], Match{
				TrackIdx: ti,
				Offset:   entry.Index,
			})
		}
	}

	fmt.Printf("[搜索] 索引加载完成: %d 首曲目, %d 个独立 hash\n",
		len(tracks), len(idx.m))
	return idx, nil
}

// Search 在索引中搜索一个指纹
func (idx *Index) Search(queryHashes []HashEntry) []SearchResult {
	qh := make(map[uint64]bool)
	for _, h := range queryHashes {
		qh[h.Hash] = true
	}

	// 统计每首轨道匹配了多少 hash
	type trackMatch struct {
		trackIdx   int
		matchCount int
		offsets    map[int]int // offset → count (留作时间一致性,暂不用)
	}
	matchMap := make(map[int]*trackMatch)

	for _, h := range queryHashes {
		if matches, ok := idx.m[h.Hash]; ok {
			for _, m := range matches {
				if _, ok := matchMap[m.TrackIdx]; !ok {
					matchMap[m.TrackIdx] = &trackMatch{
						trackIdx: m.TrackIdx,
						offsets:  make(map[int]int),
					}
				}
				tm := matchMap[m.TrackIdx]
				tm.matchCount++
				tm.offsets[m.Offset]++
			}
		}
	}

	// 计算 containment 和 Jaccard
	results := make([]SearchResult, 0, len(matchMap))
	queryHashCount := len(queryHashes)

	for _, tm := range matchMap {
		track := idx.Tracks[tm.trackIdx]
		trackHashes := make(map[uint64]bool)
		for _, h := range track.Hashes {
			trackHashes[h.Hash] = true
		}

		// 交集中有多少个 hash
		intersection := 0
		for h := range qh {
			if trackHashes[h] {
				intersection++
			}
		}

		containment := float64(intersection) / float64(queryHashCount)
		union := float64(len(qh) + len(trackHashes) - intersection)
		jaccard := float64(intersection) / max(union, 1.0)

		results = append(results, SearchResult{
			Track:       track.Track,
			MatchCount:  tm.matchCount,
			Containment: math.Round(containment*10000) / 10000,
			Jaccard:     math.Round(jaccard*10000) / 10000,
		})
	}

	sort.Slice(results, func(i, j int) bool {
		return results[i].Containment > results[j].Containment
	})

	return results
}

func max(a, b float64) float64 {
	if a > b {
		return a
	}
	return b
}
