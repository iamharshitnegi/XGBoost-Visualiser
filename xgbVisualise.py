import numpy as np
from collections import Counter
import copy
from sklearn.datasets import load_breast_cancer
from sklearn.model_selection import train_test_split
import graphviz

# Load breastCancer dataset
breastCancer = load_breast_cancer()
X, y = breastCancer.data, breastCancer.target

print(len(X[0]))
print(len(y))

#exit()
# Split the data into training and testing sets
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

visEstimators=[]

def visualize_tree(node, dot, parent=None):
    if isinstance(node, dict):
        fid = node.get('fid')
        split_point = node.get('split_point')
        gain = node.get('gain')
        label = f"fid: {fid}\nsplit_point: {split_point:.5f}\ngain: {gain:.5f}"
        current_node = str(id(node))
        
        if parent is not None:
            dot.edge(parent, current_node)
        
        dot.node(current_node, label)
        
        if 'left' in node:
            visualize_tree(node['left'], dot, current_node)
        
        if 'right' in node:
            visualize_tree(node['right'], dot, current_node)
    else:
        label = f"Value: {node}"
        current_node = str(id(node))
        dot.node(current_node, label)
        if parent is not None:
            dot.edge(parent, current_node)

def visualize(data,i):
    dot = graphviz.Digraph()
    visualize_tree(data, dot)
    dot.render(f'tree_{i}', view=False)


class MyXGBClassificationTree:
    def __init__(self, max_depth, reg_lambda, prune_gamma):
        self.max_depth = max_depth  # depth of the tree
        self.reg_lambda = reg_lambda  # regularization constant
        self.prune_gamma = prune_gamma  # pruning constant
        self.estimator1 = None  # tree result-1
        self.estimator2 = None  # tree result-2
        self.feature = None  # feature x
        self.residual = None  # residuals
        self.prev_yhat = None  # previous y_hat

    def node_split(self, did):
        r = self.reg_lambda
        max_gain = -np.inf
        d = self.feature.shape[1]  # feature dimension
        G = self.residual[did].sum()  # G before split
        H = (self.prev_yhat[did] * (1. - self.prev_yhat[did])).sum()
        p_score = (G ** 2) / (H + r+1e-10)  # score before the split

        for k in range(d):
            GL = HL = 0.0
            # split x_feat using the best feature and the best
            # split point. The code below is inefficient because
            # it sorts x_feat every time it is split.
            # Future improvements are needed.
            x_feat = self.feature[did, k]
            # remove duplicates of x_feat and sort in ascending order
            x_uniq = np.unique(x_feat)
            s_point = [np.mean([x_uniq[i - 1], x_uniq[i]]) for i in range(1, len(x_uniq))]
            l_bound = -np.inf  # lower left bound
            for j in s_point:
                # split x_feat into the left and the right node.
                left = did[np.where(np.logical_and(x_feat > l_bound, x_feat <= j))[0]]
                right = did[np.where(x_feat > j)[0]]
                # Calculate the scores after splitting
                GL += self.residual[left].sum()
                HL += (self.prev_yhat[left] * (1. - self.prev_yhat[left])).sum()
                GR = G - GL
                HR = H - HL
                # Calculate gain for this split
                gain = (GL ** 2) / (HL + r+1e-10) + (GR ** 2) / (HR + r+1e-10) - p_score
                # find the point where the gain is greatest.
                if gain > max_gain:
                    max_gain = gain
                    b_fid = k  # best feature id
                    b_point = j  # best split point
                l_bound = j

        if max_gain >= self.prune_gamma:
            # split the node using the best split point
            x_feat = self.feature[did, b_fid]
            b_left = did[np.where(x_feat <= b_point)[0]]
            b_right = did[np.where(x_feat > b_point)[0]]
            return {'fid': b_fid, 'split_point': b_point, 'gain': max_gain, 'left': b_left, 'right': b_right}
        else:
            return np.nan  # no split

    # Create a binary tree using recursion
    def recursive_split(self, node, curr_depth):
        left = node['left']
        right = node['right']
        # exit recursion
        if curr_depth >= self.max_depth:
            return
        # process recursion
        s = self.node_split(left)
        if isinstance(s, dict):  # split
            node['left'] = s
            self.recursive_split(node['left'], curr_depth + 1)
        s = self.node_split(right)
        if isinstance(s, dict):  # split
            node['right'] = s
            self.recursive_split(node['right'], curr_depth + 1)

    # Calculate the output value of a leaf node
    def output_value(self, did):
        r = self.residual[did]
        H = (self.prev_yhat[did] * (1. - self.prev_yhat[did])).sum()
        return np.sum(r) / (H + self.reg_lambda+1e-10)

    # Calculate output values for every leaf node in a tree
    def output_leaf(self, d):
        if isinstance(d, dict):
            for key, value in d.items():
                if key == 'left' or key == 'right':
                    rtn = self.output_leaf(value)
                    if rtn[0] == 1:  # leaf node
                        d[key] = rtn[1]
            return 0, 0  # first 0 = non-leaf node
        else:  # leaf node
            return 1, self.output_value(d)  # first 1 = leaf node

    # It creates a tree using the training data, and returns the
    # result of the tree. (x: feature data, y: residuals, prev_yhat: previous y_hat)
    def fit(self, x, y, prev_yhat):
        self.feature = x
        self.residual = y
        self.prev_yhat = prev_yhat  # previous y_hat.
        root = self.node_split(np.arange(x.shape[0]))
        if isinstance(root, dict):
            self.recursive_split(root, curr_depth=1)

        # tree result-1. leaf node has data indices.
        self.estimator1 = root
        # tree result-2. leaf node has its output values.
        if isinstance(self.estimator1, dict):
            self.estimator2 = copy.deepcopy(self.estimator1)
            self.output_leaf(self.estimator2)  # tree result-2
            visEstimators.append(self.estimator2)
        return self.estimator2

    # Estimate the output value of a test data point.
    def x_predict(self, p, x):
        if x[p['fid']] <= p['split_point']:
            if isinstance(p['left'], dict):
                return self.x_predict(p['left'], x)
            else:  # leaf
                return p['left']
        else:
            if isinstance(p['right'], dict):  # not a leaf
                return self.x_predict(p['right'], x)
            else:  # return the value in the leaf, if leaf.
                return p['right']

    # Estimate the output values for all x_test points.
    def predict(self, x_test):
        p = self.estimator2  # predictor
        # print(self.estimator2)
        if isinstance(p, dict):
            y_pred = [self.x_predict(p, x) for x in x_test]
            return np.array(y_pred)
        else:
            return self.prev_yhat * x_test.shape[0]


# Build XGBoost regression tree
class MyXGBClassifier:
    def __init__(self,
                 n_estimators=10, max_depth=3, learning_rate=0.5,
                 prune_gamma=0.0, reg_lambda=0.0, base_score=0.5):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.eta = learning_rate  # learning rate
        self.prune_gamma = prune_gamma  # pruning constant
        self.reg_lambda = reg_lambda  # regularization constant
        self.base_score = base_score  # initial prediction
        self.estimator1 = dict()  # tree result-1
        self.estimator2 = dict()  # tree result-2
        self.models = []
        self.loss = []

    # convert the log(odds) into probability
    def F2P(self, x):
        return 1. / (1. + np.exp(-x))

    # The same as GBM algorithm. In XGBoost, only the node
    # splitting method changes.
    def fit(self, x, y):
        # step-1: Initialize model with a constant value.
        F0 = np.log(self.base_score / (1. - self.base_score))
        Fm = np.repeat(F0, x.shape[0])
        y_hat = self.F2P(Fm)
        self.models, self.loss = [], []
        for m in range(self.n_estimators):
            # step-2 (A): Compute so-called pseudo-residuals
            residual = y - y_hat
            # step-2 (B): Fix a classification tree
            model = MyXGBClassificationTree(
                max_depth=self.max_depth,
                reg_lambda=self.reg_lambda,
                prune_gamma=self.prune_gamma)
            model.fit(x, residual, y_hat)  # y_hat: previous y_hat
            # step-2 (C): compute gamma (prediction)
            gamma = model.predict(x)
            # step-2 (D): Update the model
            Fm = Fm + self.eta * gamma
            y_hat = self.F2P(Fm)
            # save tree models
            self.models.append(model)
            # Calculate the loss = mean squared error.
        return 

    def predict(self, x_test, proba=False):
        Fm = np.zeros(shape=(x_test.shape[0],)) + self.base_score
        for model in self.models:
            Fm += self.eta * model.predict(x_test)
            y_prob = self.F2P(Fm)
            y_pred = (y_prob > 0.5).astype('uint8')
            return y_pred  # return label


# Instantiate and fit the model
xgb = MyXGBClassifier()
xgb.fit(X_train, y_train)
print(xgb.models[0].estimator2)
i=0
for data in visEstimators:
    visualize(data,i)
    i=i+1
# Test the model
y_pred = xgb.predict(X_test)
print("Test Accuracy:", np.mean(y_pred == y_test))
