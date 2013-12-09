import os, itertools, sys
from com.byond.DMI import DMI
from com.byond.directions import SOUTH, IMAGE_INDICES
from com.byond.basetypes import Atom, BYONDString, BYONDValue, BYONDFileRef
# from com.byond.objtree import ObjectTree
from PIL import Image, PngImagePlugin, ImageChops

ID_ENCODING_TABLE = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
        
def chunker(iterable, chunksize):
    """
    Return elements from the iterable in `chunksize`-ed lists. The last returned
    chunk may be smaller (if length of collection is not divisible by `chunksize`).

    >>> print list(chunker(xrange(10), 3))
    [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9]]
    """
    i = iter(iterable)
    while True:
        wrapped_chunk = [list(itertools.islice(i, int(chunksize)))]
        if not wrapped_chunk[0]:
            break
        yield wrapped_chunk.pop()

# From StackOverflow
def trim(im):
    bg = Image.new(im.mode, im.size, im.getpixel((0,0)))
    diff = ImageChops.difference(im, bg)
    diff = ImageChops.add(diff, diff, 2.0, -100)
    bbox = diff.getbbox()
    if bbox:
        return im.crop(bbox)

class Tile:
    FLAG_USE_OLD_ID = 1
    FLAG_INHERITED_PROPERTIES = 2
    
    def __init__(self):
        self.origID = ''
        self.ID = 0
        self.data = []
        self.frame = None
    
    def ID2String(self, pad=0):
        o = ''
        _id = self.ID
        IET_SIZE = len(ID_ENCODING_TABLE)
        while(_id >= len(ID_ENCODING_TABLE)):
            i = _id % IET_SIZE
            o = ID_ENCODING_TABLE[i] + o
            _id -= i
            _id /= IET_SIZE
        o = ID_ENCODING_TABLE[_id] + o
        if pad > len(o):
            o = o.rjust(pad, ID_ENCODING_TABLE[0])
        return o
    
    def __str__(self):
        return self.MapSerialize(Tile.FLAG_USE_OLD_ID)
        
    def MapSerialize(self, flags=0):
        # "aat" = (/obj/structure/grille,/obj/structure/window/reinforced{dir = 8},/obj/structure/window/reinforced{dir = 1},/obj/structure/window/reinforced,/obj/structure/cable{d1 = 2; d2 = 4; icon_state = "2-4"; tag = ""},/turf/simulated/floor/plating,/area/security/prison)
        atoms = []
        atomFlags = 0
        if flags & Tile.FLAG_INHERITED_PROPERTIES:
            atomFlags |= Atom.FLAG_INHERITED_PROPERTIES
        for i in xrange(len(self.data)):
            atom = self.data[i]
            if atom.path != '':
                atoms += [atom.MapSerialize(atomFlags)]
        if not (flags & Tile.FLAG_USE_OLD_ID):
            return '"{ID}" = ({atoms})'.format(ID=self.ID2String(), atoms=','.join(atoms))
        else:
            return '"{ID}" = ({atoms})'.format(ID=self.origID, atoms=','.join(atoms))
    
    def __eq__(self, other):
        if len(self.data) != len(other.data):
            return False
        else:
            return all(self.data[i] == other.data[i] for i in range(len(self.data)))
    
class MapLayer:
    def __init__(self, _map, height=255, width=255):
        self.map = _map
        self.min = (1, 1)
        self.max = (height, width)
        self.height = height
        self.width = width
        self.tiles = [[0 for _ in xrange(self.width)] for _ in xrange(self.height)]
        
    def SetTileAt(self, x, y, tile):
        grow = False
        if y >= self.height:
            self.height = y - 1
            grow = True
        if x >= self.width:
            self.width = x - 1
            grow = True
        if grow:
            self.grow()
        
        self.tiles[y][x] = tile.ID
    
    def grow(self):
        gamt = self.height - len(self.tiles)
        print('y+=' + str(gamt))
        self.tiles += [[0] for _ in xrange(gamt)]
        for y in range(len(self.tiles)):
            gamt = self.width - len(self.tiles[y])
            print('x[{}]+={}'.format(y, gamt))
            self.tiles[y] += [0 for _ in xrange(self.width - len(self.tiles[y]))]
        
    def GetTileAt(self, x, y):
        # print(repr(self.tiles))
        return self.map.tileTypes[self.tiles[y][x]]
    
class MapRenderFlags:
    RENDER_STARS = 1
    RENDER_AREAS = 2
    
class Map:
    WRITE_OLD_IDS = 1
    def __init__(self, tree=None):
        self.tileTypes = []
        self.zLevels = {}
        self.oldID2NewID = {}
        self.DMIs = {}
        self.width = 0
        self.height = 0
        self.idlen = 0
        self.tree = tree
    
        self.atomBorders = {
            '{':'}',
            '"':'"',
            '(':')'
        }
        nit = self.atomBorders.copy()
        for start, stop in self.atomBorders.items():
            if start != stop:
                nit[stop] = None
        self.atomBorders = nit
        
    def readMap(self, filename):
        if not os.path.isfile(filename):
            print('File ' + filename + " does not exist.")
        self.filename = filename
        with open(filename, 'r') as f:
            print('--- Reading tile types from {0}...'.format(self.filename))
            self.consumeTiles(f)
            print('--- Reading tile positions...')
            self.consumeTileMap(f)
        
    def writeMap(self, filename, flags=0):
        self.filename = filename
        tileFlags = 0
        if flags & Map.WRITE_OLD_IDS:
            tileFlags |= Tile.FLAG_USE_OLD_ID
        with open(filename, 'w') as f:
            for tile in self.tileTypes:
                f.write('{0}\n'.format(tile.MapSerialize(tileFlags)))
            for z in self.zLevels.keys():
                f.write('\n(1,1,{0}) = {{"\n'.format(z))
                zlevel = self.zLevels[z]
                for y in xrange(zlevel.height):
                    for x in xrange(zlevel.width):
                        tile = zlevel.GetTileAt(x, y)
                        if flags & Map.WRITE_OLD_IDS:
                            f.write(tile.origID)
                        else:
                            f.write(tile.ID2String(self.idlen))
                    f.write("\n")
                f.write('"}\n')
                
            
    def GetTileAt(self, x, y, z):
        if z < len(self.zLevels):
            return self.zLevels[z].GetTileAt(x, y)
        
    def consumeTileMap(self, f):
        zLevel = []
        y = 0
        z = 0
        inZLevel = False
        width = 0
        height = 0
        while True:
            line = f.readline()
            if line == '':
                return
            # (1,1,1) = {"
            if line.startswith('('):
                coordChunk = line[1:line.index(')')].split(',')
                # print(repr(coordChunk))
                z = int(coordChunk[2])
                zLevel = MapLayer(self, 255, 255)
                inZLevel = True
                y = 0
                width = 0
                height = 0
                continue
            if line.strip() == '"}':
                inZLevel = False
                if height == 0:
                    height = y
                self.zLevels[z] = zLevel
                print('Added map layer {0} ({1}x{2})'.format(z, height, width))
                continue
            if inZLevel:
                if width == 0:
                    width = len(line) / self.idlen
                x = 0
                for chunk in chunker(line.strip(), self.idlen):
                    chunk = ''.join(chunk)
                    tid = self.oldID2NewID[chunk]
                    zLevel.SetTileAt(x, y, self.tileTypes[tid])
                    x += 1
                y += 1
                
    def generateImage(self, filename_tpl, basedir='.', renderflags=0, **kwargs):
        icons = {}
        dmis = {}
        area = None
        if 'area' in kwargs:
            area = kwargs['area']
            print('area = ' + repr(area))
        print('--- Generating texture atlas...')
        for tid in xrange(len(self.tileTypes)):
            tile = self.tileTypes[tid]
            img = Image.new('RGBA', (96, 96))
            tile.offset = (32, 32)
            tile.areaSelected = True
            for atom in sorted(tile.data, reverse=True):
                
                aid = tile.data.index(atom)
                # Ignore /areas.  They look like ass.
                if atom.path.startswith('/area'):
                    if area is not None:
                        if area != atom.path:
                            tile.areaSelected = False
                            # Not in a desired area, bail.
                            break
                    if not (renderflags & MapRenderFlags.RENDER_AREAS):
                        continue
                
                # We're going to turn space black for smaller images.
                if atom.path == '/turf/space':
                    if not (renderflags & MapRenderFlags.RENDER_STARS):
                        continue
                    
                if 'icon' not in atom.properties:
                    print('CRITICAL: UNKNOWN ICON IN {0} (atom #{1})'.format(tile.origID, aid))
                    print(atom.MapSerialize())
                    print(atom.MapSerialize(Atom.FLAG_INHERITED_PROPERTIES))
                    continue
                
                dmi_file = atom.properties['icon'].value
                
                if 'icon_state' not in atom.properties:
                    # Grab default icon_state ('') if we can't find the one defined.
                    atom.properties['icon_state'] = BYONDString("")
                
                state = atom.properties['icon_state'].value
                
                direction = SOUTH
                if 'dir' in atom.properties:
                    try:
                        direction = int(atom.properties['dir'].value)
                    except ValueError:
                        print('FAILED TO READ dir = ' + repr(atom.properties['dir'].value))
                        continue
                
                icon_key = '{0}:{1}[{2}]'.format(dmi_file, state, direction)
                if icon_key not in icons:
                    dmi_path = os.path.join(basedir, dmi_file)
                    dmi = None
                    if dmi_path in dmis:
                        dmi = dmis[dmi_path]
                    else:
                        try:
                            dmi = self.loadDMI(dmi_path)
                            dmis[dmi_path] = dmi
                        except Exception as e:
                            print(str(e))
                            for prop in ['icon', 'icon_state', 'dir']:
                                print('\t{0}'.format(atom.dumpPropInfo(prop)))
                            pass
                    
                    if dmi.img.mode not in ('RGBA', 'P'):
                        print('WARNING: {} is mode {}!'.format(dmi_file, dmi.img.mode))
                        
                    if direction not in IMAGE_INDICES:
                        print('WARNING: Unrecognized direction {} on atom {} in tile {}!'.format(direction, atom.MapSerialize(), tile.origID))
                        direction = SOUTH  # DreamMaker property editor shows dir = 2.  WTF?
                        
                    frame = dmi.getFrame(state, direction, 0)
                    if frame == None:
                        # Get the error/default state.
                        frame = dmi.getFrame("", direction, 0)
                    
                    if frame == None:
                        continue
                    
                    if frame.mode != 'RGBA':
                        frame = frame.convert("RGBA")
                        
                    pixel_x = 0
                    if 'pixel_x' in atom.properties:
                        pixel_x = int(atom.properties['pixel_x'].value)
                        
                    pixel_y = 0
                    if 'pixel_y' in atom.properties:
                        pixel_y = int(atom.properties['pixel_y'].value)
                        
                    img.paste(frame, (32 + pixel_x, 32 - pixel_y), frame)  # Add to the top of the stack.
            tile.frame = img
            self.tileTypes[tid] = tile
            
        print('--- Creating maps...')
        for z in self.zLevels.keys():
            filename = filename_tpl.replace('{z}', str(z))
            print(' -> {} ({}x{})'.format(filename, (self.zLevels[z].height + 2) * 32, (self.zLevels[z].width + 2) * 32))
            zpic = Image.new('RGBA', ((self.zLevels[z].width + 2) * 32, (self.zLevels[z].height + 2) * 32), "black")
            for y in xrange(self.zLevels[z].height):
                for x in xrange(self.zLevels[z].width):
                    tile = self.zLevels[z].GetTileAt(x, y)
                    if tile is not None:
                        if not tile.areaSelected:
                            # Skip it.
                            continue
                        x_o = 0
                        y_o = 32 - tile.frame.size[1]  # BYOND uses LOWER left as origin for some fucking reason
                        zpic.paste(tile.frame, ((x * 32) + x_o + tile.offset[0], (y * 32) + y_o + tile.offset[1], (x * 32) + tile.frame.size[0] + x_o + tile.offset[0], (y * 32) + tile.frame.size[0] + y_o + tile.offset[1]), tile.frame)
                        
            # Autocrop (only works if NOT rendering stars)
            zpic = trim(zpic)
            
            if zpic is not None:
                # Saev
                zpic.save(filename, 'PNG')
            
    def loadDMI(self, filename):
        if filename not in self.DMIs:
            self.DMIs[filename] = DMI(filename)
            self.DMIs[filename].loadAll()
        return self.DMIs[filename]
    
    def cleanTile(self, t):
        for i in xrange(len(t.data)):
            if t.data[i] and 'tag' in t.data[i].properties:
                del t.data[i].properties['tag']
        return t
            
    # TODO: THIS IS GODAWFULLY SLOW
    def consumeTiles(self, f):
        index = 0
        duplicates = 0
        # self.tileTypes = [Tile() for _ in xrange(10000)]
        lineNumber = 0
        while True:
            line = f.readline()
            lineNumber += 1
            if line.startswith('"'):
                t = Tile()
                t.origID = self.consumeTileID(line)
                t.data = self.consumeTileAtoms(line.strip()[line.index('(') + 1:-1], lineNumber)
                t.ID = index
                tid = self.getTileTypeID(t)
                if tid == None:
                    self.tileTypes += [t]
                    self.idlen = max(self.idlen, len(t.ID2String()))
                    self.oldID2NewID[t.origID] = t.ID
                    index += 1
                    if((index % 100) == 0):
                        print(index)
                else:
                    print('{} duplicate of {}! Installing redirect...'.format(t.origID, tid))
                    self.oldID2NewID[t.origID] = tid
                    print(t)
                    print(self.tileTypes[tid])
                    duplicates += 1
            else:
                print('-- {} tiles loaded, {} duplicates discarded'.format(index, duplicates))
                return 
    def getTileTypeID(self, t):
        for tile in self.tileTypes:
            if tile == t:
                return tile.ID
        return None
    
    def consumeTileID(self, line):
        e = line.index('"', 1)
        return line[1:e]
    
    # So we can read a map without parsing the tree.
    def GetAtom(self, path):
        if self.tree is not None:
            return self.tree.GetAtom(path)
        return Atom(path)
    
    def consumeTileAtoms(self, line, lineNumber):
        atoms = []
        atom_chunks = self.SplitAtoms(line)
        # print(line)
        # print(repr(atom_chunks))
        for atom_chunk in atom_chunks:
            atoms += [self.consumeAtom(atom_chunk, lineNumber)]
        
        # if '{' in line:
        #    sys.exit()
        return atoms
    
    def SplitProperties(self, string):
        o = []
        buf = []
        inString = False
        # print('>>> {0}'.format(string))
        for chunk in string.split(';'):
            # print(chunk)
            if not inString:
                # chunk="REMOVE ME"
                # print('o='+repr(o))
                if '"' in chunk:
                    inString = False
                    pos = 0
                    while(True):
                        pos = chunk.find('"', pos)
                        # print('{0}: {1}'.format(pos,chunk[pos:]))
                        if pos == -1:
                            break
                        pc = ''
                        if pos > 0:
                            pc = chunk[pos - 1]
                        # print(pc)
                        if pc != '\\':
                            inString = not inString
                        pos += 1
                    if not inString:
                        o += [chunk]
                    else:
                        buf += [chunk]
                else:
                    o += [chunk]
            else:
                if '"' in chunk:
                    o += [';'.join(buf + [chunk])]
                    inString = False
                    buf = []
                else:
                    buf += [chunk]
        return o
    
    def SplitAtoms(self, string):
        ignoreLevel = []
        
        o = []
        buf = ''
        
        string = string.rstrip()
        line_len = len(string)
        for i in xrange(line_len):
            c = string[i]
            pc = ''
            if i > 0:
                pc = string[i - 1]
            
            if c in self.atomBorders and pc != '\\':
                end = self.atomBorders[c]
                if end == c:  # Just toggle.
                    if len(ignoreLevel) > 0:
                        if ignoreLevel[-1] == c:
                            ignoreLevel.pop()
                            # print('POP '+c)
                        else:
                            ignoreLevel.append(c)
                            # print('PUSH '+c)
                else:
                    if end == None:
                        if len(ignoreLevel) > 0:
                            if ignoreLevel[-1] == c:
                                ignoreLevel.pop()
                                # print('POP '+c)
                    else:
                        ignoreLevel.append(end)
                        # print('PUSH '+end)
            if c == ',' and len(ignoreLevel) == 0:
                o += [buf]
                buf = ''
            else:
                buf += c
                    
        if len(ignoreLevel) > 0:
            print(repr(ignoreLevel))
            sys.exit()
        return o + [buf]
    
    def consumeAtom(self, line, lineNumber):
        if '{' not in line:
            currentAtom = self.GetAtom(line.strip())
            if currentAtom is not None:
                return currentAtom.copy()
        chunks = line.split('{')
        currentAtom = self.GetAtom(chunks[0].strip())
        if currentAtom is not None:
            currentAtom = currentAtom.copy()
        if chunks[1].endswith('}'):
            chunks[1] = chunks[1][:-1]
        property_chunks = self.SplitProperties(chunks[1])
        for chunk in property_chunks:
            if chunk.endswith('}'):
                chunk = chunk[:-1]
            pparts = chunk.split(' = ', 1)
            key = pparts[0].strip()
            value = pparts[1].strip()
            data = self.consumeDataValue(value, lineNumber)
            
            currentAtom.properties[key] = data
            if key not in currentAtom.mapSpecified:
                currentAtom.mapSpecified += [key]
                
        # Compare to base
        currentAtom.SetLayer()
        # currentAtom.mapSpecified = []
        base_atom = self.GetAtom(currentAtom.path)
        assert base_atom != None
        for key in base_atom.properties.keys():
            val = base_atom.properties[key]
            if key not in currentAtom.properties:
                currentAtom.properties[key] = val
        for key in currentAtom.properties.iterkeys():
            val = currentAtom.properties[key].value
            if key in base_atom.properties and val == base_atom.properties[key].value:
                if key in currentAtom.mapSpecified:
                    currentAtom.mapSpecified.remove(key)
        return currentAtom
            
    def consumeDataValue(self, value, lineNumber):
        data = None
        if value[0] in ('"', "'"):
            quote = value[0]
            if quote == '"':
                data = BYONDString(value[1:-1], self.filename, lineNumber)
            elif quote == "'":
                data = BYONDFileRef(value[1:-1], self.filename, lineNumber)
        else:
            data = BYONDValue(value, self.filename, lineNumber)
        return data
    
