import numpy as np
from collections import namedtuple


def cosine_similarity(u, v, eps=1e-8):
    return np.dot(np.squeeze(u), np.squeeze(v)) / (np.linalg.norm(u) * np.linalg.norm(v) + eps)


Batch = namedtuple("Batch", ["obs", "actions", "manager_returns", "worker_returns", "s_diff", "ri", "g_in", "gsum",
                             "g_prev", "idx", "features"])


class DeepFeudalBatch:
    def __init__(self):
        self.obs = {
            "screen": [],
            "minimap": [],
            "non_spatial": []
        }

        self.actions = {
            "non_spatial": [],
            "spatial": []
        }

        self.manager_returns = []
        self.worker_returns = []

        self.s_diff = []

        self.ri = []
        self.g = []
        self.g_in = []
        self.gsum = []
        self.g_prev = []

        self.idx = []
        self.features = []

    def add(self,
            screen_obs, minimap_obs, non_spatial_obs,
            act_id, act_target,
            manager_returns, worker_returns,
            s_diff,
            ri, g, gsum, g_prev,
            idx, features):
        self.obs["screen"] += [screen_obs]
        self.obs["minimap"] += [minimap_obs]
        self.obs["non_spatial"] += [non_spatial_obs]

        self.actions["non_spatial"] += [act_id]
        self.actions["spatial"] += [act_target]

        self.manager_returns += [manager_returns]
        self.worker_returns += [worker_returns]

        self.s_diff += [s_diff]
        self.ri += [ri]
        self.g += [g]
        self.gsum += [gsum]
        self.g_prev += [g_prev]

        self.idx += [idx]
        self.features += [features]

    def get_batch(self):
        batch_idx = np.asarray(self.idx)
        batch_g_in = np.asarray(self.g)
        if len(batch_g_in.shape) > 2:
            batch_g_in = np.squeeze(batch_g_in)
        if len(batch_g_in.shape) < 2:
            batch_g_in = np.expand_dims(batch_g_in, 0)
        batch_g_prev = np.asarray(self.g_prev)

        if len(batch_g_prev.shape) > 3:
            batch_g_prev = np.squeeze(batch_g_prev)
        if len(batch_g_prev.shape) < 3:
            batch_g_prev = np.expand_dims(batch_g_prev, 0)

        sums = []

        for i in range(len(batch_g_prev)):
            sums.append(np.sum(batch_g_prev[i], axis=0))

        batch_manager_returns = np.asarray(self.manager_returns)
        batch_worker_returns = np.asarray(self.worker_returns)
        batch_sd = np.asarray(self.s_diff)
        if len(batch_sd.shape) >= 2 and batch_sd.shape[1] == 1:
            batch_sd = np.squeeze(batch_sd, axis=1)
        batch_ri = np.asarray(self.ri)
        batch_gs = np.asarray(sums)
        return Batch(self.obs, self.actions,
                     batch_manager_returns, batch_worker_returns,
                     batch_sd, batch_ri, batch_g_in, batch_gs, batch_g_prev,
                     batch_idx[0], self.features[0])


class DeepFeudalBatchProcessor:
    def __init__(self, c):
        self.c = c
        self.last_terminal = True

        self.obs = {
            "screen": [],
            "minimap": [],
            "non_spatial": []
        }
        self.actions = {
            "non_spatial": [],
            "spatial": []
        }

        self.manager_returns = []
        self.worker_returns = []
        self.s = []
        self.g = []
        self.features = []

    def _pad_front(self, batch):
        self.s = [np.zeros_like(batch.s[0]) for _ in range(self.c)]
        self.g = [np.zeros_like(batch.g[0]) for _ in range(self.c)]

        screen_obs_shape = list(np.shape(batch.obs["screen"]))
        minimap_obs_shape = list(np.shape(batch.obs["minimap"]))
        non_spatial_obs_shape = list(np.shape(batch.obs["non_spatial"]))
        screen_obs_shape[0] = minimap_obs_shape[0] = non_spatial_obs_shape[0] = self.c

        # prepend with dummy values so indexing is the same
        self.obs["screen"] = list(np.zeros(screen_obs_shape))
        self.obs["minimap"] = list(np.zeros(minimap_obs_shape))
        self.obs["non_spatial"] = list(np.zeros(non_spatial_obs_shape))

        self.actions["spatial"] = [None for _ in range(self.c)]
        self.actions["non_spatial"] = [None for _ in range(self.c)]

        self.g_save = [None for _ in range(self.c)]
        self.g_prev = [None for _ in range(self.c)]
        self.idx = [None for _ in range(self.c)]
        self.manager_returns = [None for _ in range(self.c)]
        self.worker_returns = [None for _ in range(self.c)]
        self.features = [None for _ in range(self.c)]

    def _pad_back(self, batch):
        self.s.extend([np.zeros_like(batch.s[-1]) for _ in range(self.c)])
        self.g.extend([np.zeros_like(batch.g[-1]) for _ in range(self.c)])

    def _extend(self, batch):
        if self.last_terminal:
            self.last_terminal = False
            self._pad_front(batch)

        # extend with the actual values
        self.obs['screen'].extend(batch.obs["screen"])
        self.obs['minimap'].extend(batch.obs["minimap"])
        self.obs['non_spatial'].extend(batch.obs["non_spatial"])

        self.actions["spatial"].extend(batch.actions["spatial"])
        self.actions["non_spatial"].extend(batch.actions["non_spatial"])

        self.g_save.extend(batch.g)
        self.idx.extend(batch.idx)
        self.g_prev.extend(batch.g_prev)
        self.manager_returns.extend(batch.manager_returns)
        self.worker_returns.extend(batch.worker_returns)
        self.s.extend(batch.s)
        self.g.extend(batch.g)
        self.features.extend(batch.features)

        # if this is a terminal batch, then append the final s and g c times
        # note that both this and the above case can occur at the same time
        if batch.terminal:
            self._pad_back(batch)

    def process_batch(self, batch):
        self._extend(batch)

        length = len(self.obs['screen'])
        c = self.c
        end = length if batch.terminal else length - c

        feudal_batch = DeepFeudalBatch()
        for t in range(c, end):
            s_diff = self.s[t + c] - self.s[t]
            ri = 0
            for i in range(1, c + 1):
                ri += cosine_similarity(self.s[t] - self.s[t - i], self.g[t - i])
            ri /= c

            gsum = np.zeros_like(self.g[t - c])
            for i in range(t - c, t + 1):
                gsum += self.g[i]

            feudal_batch.add(
                self.obs["screen"][t], self.obs["minimap"][t], self.obs["non_spatial"][t],
                self.actions["non_spatial"][t], self.actions["spatial"][t],
                self.manager_returns[t], self.worker_returns[t],
                s_diff, ri, self.g_save[t], gsum, self.g_prev[t],
                self.idx[t], self.features[t]
            )

        if batch.terminal:
            self.last_terminal = True
        else:
            twoc = 2 * self.c
            self.obs["screen"] = self.obs["screen"][-twoc:]
            self.obs["minimap"] = self.obs["minimap"][-twoc:]
            self.obs["non_spatial"] = self.obs["non_spatial"][-twoc:]

            self.actions["spatial"] = self.actions["spatial"][-twoc:]
            self.actions["non_spatial"] = self.actions["non_spatial"][-twoc:]

            self.manager_returns = self.manager_returns[-twoc:]
            self.worker_returns = self.manager_returns[-twoc:]
            self.s = self.s[-twoc:]
            self.g = self.g[-twoc:]
            self.features = self.features[-twoc:]

        return feudal_batch.get_batch()
