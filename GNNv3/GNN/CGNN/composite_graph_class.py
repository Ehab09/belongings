from __future__ import annotations
from typing import Optional
import networkx as nx
import matplotlib.pyplot as plt

import numpy as np


#######################################################################################################################
## GRAPH OBJECT CLASS #################################################################################################
#######################################################################################################################
class CompositeGraphObject:
	## CONSTRUCTORS METHODS ###########################################################################################
	def __init__(self, arcs: np.array, nodes: np.array, targets: np.array, problem_based: str = 'n',
				 set_mask: Optional[np.array] = None, output_mask: Optional[np.array] = None, type_mask: Optional[np.array] = None,
				 NodeGraph: Optional[np.array] = None, ArcNode: Optional[np.array] = None,
				 node_aggregation: str = "average") -> None:
		""" CONSTRUCTOR METHOD
		:param arcs: Ordered Arcs Matrix where arcs[i,:] = [ID Node From | ID NodeTo | Arc Label]
		:param nodes: Ordered Nodes Matrix where nodes[i,:] = [Node Label]
		:param targets: Targets Array with shape (Num of targeted example {nodes|arcs|(1|2+ if merged)}, dim_target)
		:param problem_based: (str) define the type of problem: 'a' arcs-based, 'g' graph-based, 'n' node-based
		:param set_mask: Array of {0,1} to define arcs/nodes belonging to a set, when dataset == single CompositeGraphObject
		:param output_mask: Array of {0,1} to define the sub-set of arcs/nodes whose output is needed
		:param type_mask: Matrix (nodes.shape[0], #types) of {0,1} masks to define which nodes belong to each type
		:param NodeGraph: Matrix (nodes.shape[0],{Num graphs|1}) s.t. node-based problem -> graph-based one
		:param ArcNode: Matrix of shape (num_of_arcs, num_of_nodes) s.t. A[i,j]=value if arc[i,2]==node[j]
		:param node_aggregation: (str) in ['average', 'sum' or 'normalized']. How to perform node_aggregation.
		"""
		# store arcs, nodes, targets
		self.arcs = arcs
		self.nodes = nodes
		self.targets = targets

		# setting the problem type: node, arcs or graph based + check existence of passed parameters in keys
		lenMask = {'n': nodes.shape[0], 'a': arcs.shape[0], 'g': nodes.shape[0]}
		self.problem_based = problem_based

		# build set_mask, for a dataset composed of only a single graph: its nodes have to be divided in Tr, Va and Te
		self.set_mask = np.ones(lenMask[self.problem_based]) if set_mask is None else set_mask

		# build output_mask
		self.output_mask = np.ones(len(self.set_mask)) if output_mask is None else output_mask

		# build type_mask
		self.type_mask = np.ones((lenMask[self.problem_based], 1)) if type_mask is None else type_mask

		# check lengths: output_mask must be as long as set_mask
		if not len(self.set_mask) == len(self.output_mask):
			raise ValueError('Error - len(<set_mask>) != len(<output_mask>)')

		# build node_graph conversion matrix
		self.NodeGraph = self.buildNodeGraph() if NodeGraph is None else NodeGraph

		# build ArcNode tensor or acquire it from input
		self.ArcNode = self.buildArcNode(node_aggregation=node_aggregation) if ArcNode is None else ArcNode

	# -----------------------------------------------------------------------------------------------------------------
	def copy(self) -> 'CompositeGraphObject':
		""" COPY METHOD, return a Deep Copy of the Graph Object instance """
		return CompositeGraphObject(arcs=self.getArcs(), nodes=self.getNodes(), targets=self.getTargets(),
						   problem_based=self.getProblemBased(), set_mask=self.getSetMask(),
						   output_mask=self.getOutputMask(), type_mask=self.getTypeMask(), 
						   NodeGraph=self.getNodeGraph(), ArcNode=self.getArcNode())

	# -----------------------------------------------------------------------------------------------------------------
	def buildAdiacencyMatrix(self):
		""" Build Adjacency Matrix ADJ of the graph, s.t.  ADJ[i,j]=1 if edge (i,j) exists """
		from scipy.sparse import coo_matrix
		values = np.ones(self.arcs.shape[0], dtype=np.float32)
		indices = self.arcs[:, :2].astype(int)
		return coo_matrix((values, (indices[:, 0], indices[:, 1])), shape=(len(self.nodes), len(self.nodes)), dtype=np.float32)

	# -----------------------------------------------------------------------------------------------------------------
	def buildNodeGraph(self) -> np.array:
		""" Build Node-Graph Aggregation Matrix, to transform a node-based problem in a graph-based one.
		It has dimensions (nodes.shape[0], 1) for one graph, or (nodes.shape[0], Num graphs) for a graph containing
		2+ graphs, built by merging the single graphs into a bigger one, such that after the node-graph aggregation
		process gnn can compute (Num graphs, targets.shape[1]) as output.
		It's normalized wrt the number of nodes whose output is computed, i.e. the number of ones in output_mask
		:return: node-graph matrix
		"""
		nodes_output_coefficient = self.nodes.shape[0]  # if normalized wrt the number of nodes in the graph
		# nodes_output_coefficient = np.count_nonzero(self.output_mask)
		return np.ones((nodes_output_coefficient, 1)) * 1 / nodes_output_coefficient

	# -----------------------------------------------------------------------------------------------------------------
	def buildArcNode(self, node_aggregation: str):
		""" Build ArcNode Matrix A of shape (number_of_arcs, number_of_nodes) where A[i,j]=value if arc[i,2]==node[j]
		Compute the matmul(m:=message,A) to get the incoming message on each node
		:param node_aggregation: (str) It defines the aggregation mode for the incoming message of a node:
			> 'average': elem(A)={0-1} -> matmul(m,A) gives the average of incoming messages, s.t. sum(A[:,i])=1
			> 'normalized': elem(A)={0-1} -> matmul(m,A) gives the normalized message wrt the total number of g.nodes
			> 'sum': elem(A)={0,1} -> matmul(m,A) gives the total sum of incoming messages
		:return: sparse ArcNode Matrix, for memory efficiency
		:raise: Error if <node_aggregation> is not in ['average','sum','normalized']
		"""
		col = self.arcs[:, 1]  # column indices of A are located in the second column of the arcs tensor
		row = np.arange(0, len(col))  # arc id (from 0 to #arcs)
		values_vector = np.ones(len(col))
		val, col_index, destination_node_counts = np.unique(col, return_inverse=True, return_counts=True)
		if node_aggregation == "average": values_vector = values_vector / destination_node_counts[col_index]
		elif node_aggregation == "normalized": values_vector = values_vector * float(1 / float(len(col)))
		elif node_aggregation == "sum": pass
		else: raise ValueError("ERROR: Unknown aggregation mode")
		# isolated nodes correction: if nodes[i] is isolated, then ArcNode[:,i]=0, to maintain nodes ordering
		from scipy.sparse import coo_matrix
		return coo_matrix((values_vector, (row, self.arcs[:, 1])), shape=(len(self.arcs), len(self.nodes)))

	## SETTERS ########################################################################################################
	def setArcNode(self, node_aggregation: str) -> None:
		""" set self.ArcNode for a different node_aggregation method """
		self.ArcNode = self.buildArcNode(node_aggregation=node_aggregation)

	## GETTERS ########################################################################################################
	# return copies. NOTE: initState(v) return a zeros matrix of shape (num_nodes,v) OR the node_label matrix if v==0
	def getArcs(self):			   return self.arcs.copy()
	def getNodes(self):			  return self.nodes.copy()
	def getTargets(self):			return self.targets.copy()
	def getProblemBased(self):	   return self.problem_based[:]
	def getSetMask(self):			return self.set_mask.copy()
	def getOutputMask(self):		 return self.output_mask.copy()
	def getTypeMask(self):		   return self.type_mask.copy()
	def getArcNode(self):			return self.ArcNode.copy()
	def getNodeGraph(self):		  return self.NodeGraph.copy()
	#def initState(self, v: int = 0): return np.zeros((self.nodes.shape[0], v)) if v > 0 else self.nodes.copy()

	## STATIC METHODS #################################################################################################
	@staticmethod
	def load(graph_folder_path: str, problem_based: str, *, node_aggregation: str = "average") -> 'CompositeGraphObject':
		""" Load a graph from a directory which contains at least 3 txt files referring to nodes, arcs and targets
			NOTE Other possible files in directory: 'NodeGraph.txt','output_mask.txt' and 'set_mask.txt'.
			NOTE For graph_based problems, 'NodeGraph.txt' must be in folder
		:param graph_folder_path: (str) dir containing at least 3 files: 'nodes.txt', 'arcs.txt' and 'targets.txt'
		:param node_aggregation: node aggregation mode: 'average','sum','normalized'. See BuildArcNode for details
		:param problem_based: (str) 'n' nodeBased; 'a' arcBased; 'g' graphBased. See CONSTRUCTOR __init__ for details
		:return: CompositeGraphObject described by the files contained inside <graph_folder_path> folder
		"""
		import os
		# load all the files inside <graph_folder_path> folder
		if graph_folder_path[-1] != '/': graph_folder_path += '/'
		files = sorted(os.listdir(graph_folder_path))
		keys = [i.rsplit('.')[0] for i in files] + ['problem_based', 'node_aggregation']
		vals = [np.loadtxt(graph_folder_path + i, delimiter=',', ndmin=2) for i in files] + [problem_based, node_aggregation]
		# create a dictionary with parameters and values to be passed to constructor and return CompositeGraphObject
		params = dict(zip(keys, vals))
		return CompositeGraphObject(**params)

	# -----------------------------------------------------------------------------------------------------------------
	@staticmethod
	def save(graph_folder_path: str, g: 'CompositeGraphObject', *, save_set_mask: bool = False, save_type_mask: bool=True, format: str = '%.10g') -> None:
		""" Save a graph to a directory, creating txt files referring to nodes, arcs, targets, and masks
		:param graph_folder_path: new directory for saving the graph
		:param g: graph of type CompositeGraphObject to be saved
		:param save_set_mask: (bool) if True, save also g.set_mask, by default a graph is loaded with set_mask==ones
		:param format: param to be passed to np.savetxt
		"""
		import os, shutil
		if graph_folder_path[-1] != '/': graph_folder_path += '/'
		if os.path.exists(graph_folder_path): shutil.rmtree(graph_folder_path)
		os.makedirs(graph_folder_path)
		np.savetxt(graph_folder_path + "arcs.txt", g.arcs, fmt=format, delimiter=',')
		np.savetxt(graph_folder_path + "nodes.txt", g.nodes, fmt=format, delimiter=',')
		np.savetxt(graph_folder_path + "targets.txt", g.targets, fmt=format, delimiter=',')
		if save_set_mask:
			np.savetxt(graph_folder_path + "set_mask.txt", g.set_mask, fmt=format, delimiter=',')
		if not np.array_equal(g.output_mask, np.ones(len(g.output_mask))):
			np.savetxt(graph_folder_path + "out_mask.txt", g.output_mask, fmt=format, delimiter=',')
		if save_type_mask:
			np.savetxt(graph_folder_path + "type_mask.txt", g.type_mask, fmt=format, delimiter=',')
		if g.problem_based == 'g' and g.targets.shape[0] > 1:
			np.savetxt(graph_folder_path + 'NodeGraph.txt', g.NodeGraph, fmt=format, delimiter=',')

	# -----------------------------------------------------------------------------------------------------------------
	@staticmethod
	def merge(glist: list['CompositeGraphObject'], node_aggregation: str) -> 'CompositeGraphObject':
		""" Method to merge graphs: it takes in input a list of graphs and returns them as a single graph
		:param glist: list of CompositeGraphObjects.
						NOTE If problem_based=='g', NodeGraph.shape==(Num nodes, Num graphs), else (Num nodes,1)
		:return: a new CompositeGraphObject containing all the information (nodes, arcs, targets) in g_list
		"""
		# check parameters
		if type(glist) != list or not all(isinstance(x, CompositeGraphObject) for x in glist):
			raise TypeError('type of param <glist> must be list of CompositeGraphObjects')
		# check problem_based parameter for all the graphs. Take the lost(set of all problem type in glist).
		problem_based_set = list({i.problem_based for i in glist})
		if problem_based_set == []: return None
		elif len(problem_based_set) != 1 or problem_based_set[0] not in ['n', 'a', 'g']:
			raise ValueError('All graphs in <glist> must have the same <g.problem_based> parameter in [n,a,g]')
		# retrieve problem type and all the useful entities -> tuple
		problem_based = problem_based_set.pop()
		nodes, arcs, targets, setmask, outmask, typemask = zip(*[(i.getNodes(), i.getArcs(), i.getTargets(), i.getSetMask(), i.getOutputMask(), i.getTypeMask()) for i in glist])
		# adjust nodes_index in arcs
		nodes_lens = [i.shape[0] for i in nodes]
		for i, elem in enumerate(arcs): elem[:, :2] += sum(nodes_lens[:i])
		# concatenate all the tuples to have a single array per entity
		nodes = np.concatenate(nodes, axis=0)
		arcs = np.concatenate(arcs, axis=0)
		targets = np.concatenate(targets, axis=0)
		setmask = np.concatenate(setmask, axis=0)
		outmask = np.concatenate(outmask, axis=0)
		typemask = np.concatenate(typemask, axis=0)
		# nodegraph matrix
		nodegraph = None
		if problem_based == 'g':
			from scipy.linalg import block_diag
			nodegraph = [i.getNodeGraph() for i in glist]
			nodegraph = block_diag(*nodegraph)
		# returning CompositeGraphObject
		return CompositeGraphObject(arcs=arcs, nodes=nodes, targets=targets, set_mask=setmask, 
						   output_mask=outmask, type_mask=typemask, problem_based=problem_based, 
						   NodeGraph=nodegraph, node_aggregation=node_aggregation)
	# def plot_graph(self):
	# 	""" دالة لعرض الرسم البياني باستخدام مكتبة NetworkX و Matplotlib """
	# 	G = nx.DiGraph()  # ننشئ رسم بياني موجه

	# 	# إضافة العقد إلى الرسم البياني
	# 	for i, node in enumerate(self.nodes):
	# 		G.add_node(i, label=node[0])

	# 	# إضافة الحواف بين العقد بناءً على مصفوفة arcs
	# 	for arc in self.arcs:
	# 		from_node, to_node, label = int(arc[0]), int(arc[1]), arc[2]
	# 		G.add_edge(from_node, to_node, label=label)

	# 	# رسم الرسم البياني مع تسميات العقد والحواف
	# 	pos = nx.spring_layout(G)  # تحديد تنسيق الرسم البياني
	# 	nx.draw(G, pos, with_labels=True, node_size=500, node_color="lightblue", font_size=10, font_weight="bold", arrows=True)
		
	# 	# إضافة تسميات الحواف
	# 	edge_labels = {(int(arc[0]), int(arc[1])): arc[2] for arc in self.arcs}
	# 	nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_color="red")

	# 	# عرض الرسم البياني
	# 	plt.title("Graph Visualization")
	# 	plt.show()
