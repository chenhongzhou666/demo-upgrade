package handlers

import (
	"encoding/json"
	"net/http"
)

func Health(enginePath string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{
			"status": "ok",
			"engine": enginePath,
		})
	}
}
