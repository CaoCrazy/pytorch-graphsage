#!/usr/bin/env python

"""
    models.py
"""

from __future__ import division
from __future__ import print_function

from functools import partial

import torch
from torch import nn
from torch.nn import functional as F

# --
# Model

class GSSupervised(nn.Module):
    def __init__(self, input_dim, num_classes, layer_specs, 
        aggregator_class, prep_class, learning_rate=0.01, weight_decay=0.0):
        super(GSSupervised, self).__init__()
        
        # --
        # Network
        
        self.prep = prep_class(
            input_dim=input_dim,
        )
        
        input_dim = self.prep.output_dim
        
        agg_layers = []
        for spec in layer_specs:
            agg = aggregator_class(
                input_dim=input_dim,
                output_dim=spec['output_dim'],
                activation=spec['activation'],
            )
            agg_layers.append(agg)
            input_dim = agg.output_dim # May not be the same as spec['output_dim']
        
        self.agg_layers = nn.Sequential(*agg_layers)
        self.fc = nn.Linear(input_dim, num_classes, bias=True)
        
        # --
        # Samplers
        
        self.sampler_fns = [partial(s['sample_fn'], n_samples=s['n_samples']) for s in layer_specs]
        
        # --
        # Optimizer
        
        self.optimizer = torch.optim.Adam(self.parameters(), lr=learning_rate, weight_decay=weight_decay)
    
    def _sample(self, ids, features, adj):
        all_feats = [features[ids]]
        for sampler_fn in self.sampler_fns:
            ids = sampler_fn(ids=ids, adj=adj).contiguous().view(-1)
            all_feats.append(features[ids])
        
        return all_feats
    
    def forward(self, ids, features, adj):
        # Prep features
        features = self.prep(ids, features, adj)
        
        # Collect features for points in neighborhoods of ids
        all_feats = self._sample(ids, features, adj)
        
        # Sequentially apply layers, per original (little weird, IMO)
        # Each iteration reduces length of array by one
        for agg_layer in self.agg_layers.children():
            all_feats = [agg_layer(all_feats[k], all_feats[k + 1]) for k in range(len(all_feats) - 1)]
        
        assert len(all_feats) == 1, "len(all_feats) != 1"
        
        # out = F.normalize(all_feats[0], dim=1) # ??
        out = all_feats[0]
        return self.fc(out)
    
    def train_step(self, ids, features, adj, targets, loss_fn):
        self.optimizer.zero_grad()
        # Predict
        preds = self(ids, features, adj)
        # Make sure not (N X 1) dimensional
        targets = targets.squeeze()
        # Compute loss
        loss = loss_fn(preds, targets)
        # Update
        loss.backward()
        torch.nn.utils.clip_grad_norm(self.parameters(), 5)
        self.optimizer.step()
        return preds

